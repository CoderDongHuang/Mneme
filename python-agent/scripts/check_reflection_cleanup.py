"""Real Redis and durable DB deletion-fence acceptance on unique synthetic users.

The private stream prevents application consumers from executing test jobs.
Only the model is replaced; storage, Lua, locks and failures are real operations.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sys
from threading import Event
from unittest.mock import patch
import uuid

import redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.memory.reflection_scheduler as module  # noqa: E402
from app.knowledge.generations import GenerationStore, StaleGeneration, generation_store  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402


def check():
    user = "reflection-cleanup-qa-" + uuid.uuid4().hex
    other, nested, imported = user + "-other", user + ":nested", user + "*?[old]"
    users = (user, other, nested, imported)
    original_settings, original_reflect = module.settings, module.run_reflection
    original_queue, original_group = module._QUEUE_KEY, module._QUEUE_GROUP
    module._QUEUE_KEY += ":qa:" + uuid.uuid4().hex
    module._QUEUE_GROUP = "qa-reflection-cleanup"
    module.settings = replace(module.settings, memory_reflection_every_sessions=1)
    first, second = module.ReflectionScheduler(), module.ReflectionScheduler()
    client = first._redis
    release, started = Event(), Event()

    def residual(who):
        exact = [first._counter_key(who), first._job_key(who),
                 first._lease_key(who), first._lease_state_key(who)]
        return (client.exists(*exact), list(first._delivery_keys(who)),
                [entry for batch in first._user_queue_batches(who) for entry in batch])

    def rejected(scheduler, who):
        try:
            scheduler.record_session(who, "session", "late")
        except StaleGeneration:
            pass
        else:
            raise AssertionError("A deleted user counted a late turn")
        assert not scheduler.check_and_trigger(who)
        assert not scheduler._claim_shared(who, "job", "late-owner")
        scheduler._run_queued_reflection("1-0", {"user_id": who, "claimed_count": "1"})

    try:
        first._ensure_queue()
        for who in users:
            assert first.record_session(who, "session", "turn") == 1
            assert first.check_and_trigger(who)
        initial = client.xrange(module._QUEUE_KEY)
        identifier, values = next(entry for entry in initial if entry[1]["user_id"] == user)
        # More than two pages; pending + never-delivered entries, mixed tenants,
        # duplicate legacy jobs and delivery markers must all be covered.
        for i in range(450):
            client.xadd(module._QUEUE_KEY, {"user_id": user if i % 2 else other,
                                           "claimed_count": "1"})
        for i in range(410):
            client.set(first._delivery_key(user, "session", f"extra-{i}"), "1", ex=60)
        client.xreadgroup(module._QUEUE_GROUP, "qa-reader", {module._QUEUE_KEY: ">"}, count=300)
        protected = {who: residual(who) for who in (other, nested, imported)}

        def paused(_user):
            started.set()
            assert release.wait(20)

        module.run_reflection = paused
        with ThreadPoolExecutor(max_workers=1) as pool:
            executing = pool.submit(first._run_queued_reflection, identifier, values)
            try:
                assert started.wait(5)
                owner = client.get(first._lease_key(user))
                assert owner
                # A silent DEL must fail readback even if Stream removal worked.
                with patch.object(second._redis, "delete", return_value=0):
                    try:
                        second.delete_user(user)
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("Silent DEL was accepted")
                assert GenerationStore(generation_store.path).snapshot(user)["deleted"]
                rejected(module.ReflectionScheduler(), user)
                assert second.delete_user(user) == {"keys": 0, "queue_entries": 0}
            finally:
                release.set()
            executing.result(5)
        assert not first._complete_shared(user, 1, values["job_token"], owner, identifier)
        assert residual(user) == (0, [], [])
        assert "reflection_deliveries" not in generation_store.snapshot(user)
        assert generation_store.snapshot(other)["reflection_deliveries"]
        assert all(residual(who) == protected[who] for who in protected)
        pending = client.xpending_range(module._QUEUE_KEY, module._QUEUE_GROUP, "-", "+", 1000)
        for entry in pending:
            stored = client.xrange(module._QUEUE_KEY, entry["message_id"], entry["message_id"])
            assert stored and stored[0][1]["user_id"] != user

        # Redis errors must leave a durable denial and be retryable. No tombstone
        # rollback simply because another storage operation failed afterward.
        with patch.object(first._redis, "scan_iter", side_effect=redis.ConnectionError("scan unavailable")):
            try:
                first.delete_user(imported)
            except redis.ConnectionError:
                pass
            else:
                raise AssertionError("Scan error was swallowed")
        rejected(module.ReflectionScheduler(), imported)
        first.delete_user(imported)
        assert residual(imported) == (0, [], [])
        assert residual(nested) == protected[nested]

        evaluate = first._redis.eval

        def noop_stream(script, *args):
            return 0 if script == module._DELETE_ENTRIES_SCRIPT else evaluate(script, *args)

        with patch.object(first._redis, "eval", side_effect=noop_stream):
            try:
                first.delete_user(nested)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Silent Stream deletion was accepted")
        assert first.delete_user(nested) == {"keys": 0, "queue_entries": 0}
        assert residual(nested) == (0, [], [])
        assert residual(other) == protected[other]
        assert first.delete_user(user) == {"keys": 0, "queue_entries": 0}
        print(json.dumps({"real_redis": True, "database": module.settings.auxiliary_store_backend,
                          "paged_keys_stream_and_pending": "passed", "tenant_and_glob_isolation": "passed",
                          "inflight_owner_cannot_settle": "passed", "durable_late_replay_rejected": "passed",
                          "silent_delete_and_read_errors": "rejected", "retry_and_idempotency": "passed"}))
    finally:
        release.set()
        module.run_reflection = original_reflect
        # Exact synthetic scope only. Production tombstones are never removed.
        for who in users:
            first.delete_user(who)
            assert residual(who) == (0, [], [])
        client.delete(module._QUEUE_KEY)
        remove_probe_users(*users)
        module.settings = original_settings
        module._QUEUE_KEY, module._QUEUE_GROUP = original_queue, original_group


if __name__ == "__main__":
    check()
