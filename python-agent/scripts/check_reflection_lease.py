"""Real Redis ownership regression, scoped to a unique QA user and its entries.

Run with all application code from the target release. The model alone is
replaced inside this process; Redis, Lua, Streams and heartbeat threads are real.
"""
import json
import sys
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.memory.reflection_scheduler as module  # noqa: E402


def check():
    user = "reflection-qa-" + uuid.uuid4().hex
    first, second = module.ReflectionScheduler(), module.ReflectionScheduler()
    client = first._redis
    original_settings, original_reflect = module.settings, module.run_reflection
    original_queue, original_group = module._QUEUE_KEY, module._QUEUE_GROUP
    # A private stream on the real Redis server prevents the running app's
    # consumer from executing the synthetic QA user or stealing test entries.
    module._QUEUE_KEY = original_queue + ":qa:" + uuid.uuid4().hex
    module._QUEUE_GROUP = "qa-reflection-workers"
    module.settings = replace(module.settings, memory_reflection_every_sessions=1)
    keys = [first._counter_key(user), first._lease_key(user),
            first._lease_state_key(user), first._job_key(user)]
    entries, workers = [], []
    release = threading.Event()
    # Make the real Redis TTL short for the timing regression; production still
    # enforces at least 60 seconds. No production key/configuration is changed.
    first._lease_seconds = second._lease_seconds = lambda: 1

    def entry():
        found = [(identifier, values) for identifier, values in client.xrange(module._QUEUE_KEY)
                 if values.get("user_id") == user]
        assert len(found) == 1, "Expected exactly one reserved QA job"
        identifier, values = found[0]
        entries.append(identifier)
        # Put this exact entry in the actual consumer group's pending list.
        client.xclaim(module._QUEUE_KEY, module._QUEUE_GROUP, "qa-crashed", 0,
                      [identifier], force=True)
        return identifier, values

    try:
        assert first.record_session(user) == 1
        assert first.check_and_trigger(user)
        assert not second.check_and_trigger(user)
        identifier, values = entry()
        started = threading.Event()
        calls = []

        def slow_reflection(user_id):
            calls.append(user_id)
            started.set()
            assert release.wait(10), "QA model release timed out"

        module.run_reflection = slow_reflection
        worker = threading.Thread(target=first._run_queued_reflection, args=(identifier, values))
        workers.append(worker)
        worker.start()
        assert started.wait(5)
        owner = client.get(first._lease_key(user))
        assert owner and owner != values["job_token"]
        time.sleep(2.2)  # More than two real TTLs; renewal must keep this owner.
        assert client.get(first._lease_key(user)) == owner
        second._run_queued_reflection(identifier, values)
        assert calls == [user], "A live owner must never share execution"
        assert first.record_session(user) == 2
        release.set()
        worker.join(5)
        assert not worker.is_alive()
        assert client.get(first._counter_key(user)) == "1"
        assert not client.exists(first._job_key(user), first._lease_key(user))
        assert client.xrange(module._QUEUE_KEY, identifier, identifier) == []
        assert client.xpending_range(module._QUEUE_KEY, module._QUEUE_GROUP,
                                     identifier, identifier, 1) == []
        second._run_queued_reflection(identifier, values)
        assert calls == [user] and client.get(first._counter_key(user)) == "1"

        # A crashed owner loses its TTL; only a new token may settle the job.
        assert first.check_and_trigger(user)
        identifier, values = entry()
        job = values["job_token"]
        assert first._claim_shared(user, job, "crashed-owner")
        assert not second._claim_shared(user, job, "new-owner")
        time.sleep(1.2)
        assert second._claim_shared(user, job, "new-owner")
        assert not first._complete_shared(user, 1, job, "crashed-owner", identifier)
        assert client.get(first._counter_key(user)) == "1"
        assert second._complete_shared(user, 1, job, "new-owner", identifier)
        assert not second._complete_shared(user, 1, job, "new-owner", identifier)
        assert not client.exists(first._counter_key(user), first._job_key(user))

        # Legacy duplicate queue entries are coalesced without losing counts.
        first.record_session(user)
        first.record_session(user)
        legacy = [client.xadd(module._QUEUE_KEY, {"user_id": user, "claimed_count": "1"})
                  for _ in range(2)]
        entries.extend(legacy)
        client.set(first._lease_key(user), "old-version-owner", ex=1)
        first._run_queued_reflection(legacy[0], {"user_id": user, "claimed_count": "1"})
        assert len([v for _, v in client.xrange(module._QUEUE_KEY)
                    if v.get("user_id") == user]) == 2
        time.sleep(1.2)
        for legacy_id in legacy:
            client.xclaim(module._QUEUE_KEY, module._QUEUE_GROUP, "qa-crashed", 0,
                          [legacy_id], force=True)
            second._run_queued_reflection(legacy_id, {"user_id": user, "claimed_count": "1"})
        identifier, values = entry()
        assert values["claimed_count"] == "2"
        module.run_reflection = calls.append
        second._run_queued_reflection(identifier, values)
        assert calls == [user, user]
        assert not client.exists(first._counter_key(user), first._job_key(user))
        print(json.dumps({"real_redis": True, "heartbeat_past_ttl": "passed",
                          "live_owner_exclusion": "passed", "stale_completion": "rejected",
                          "crash_takeover": "passed", "duplicate_delivery": "passed",
                          "new_sessions_preserved": "passed", "legacy_migration": "passed"}))
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
        module.settings, module.run_reflection = original_settings, original_reflect
        # Delete only exact QA keys and entries, never the shared stream/group.
        for identifier, values in client.xrange(module._QUEUE_KEY):
            if values.get("user_id") == user:
                entries.append(identifier)
        for identifier in set(entries):
            client.xack(module._QUEUE_KEY, module._QUEUE_GROUP, identifier)
            client.xdel(module._QUEUE_KEY, identifier)
        client.delete(*keys)
        assert not client.exists(*keys)
        assert not any(values.get("user_id") == user for _, values in client.xrange(module._QUEUE_KEY))
        client.delete(module._QUEUE_KEY)
        module._QUEUE_KEY, module._QUEUE_GROUP = original_queue, original_group


if __name__ == "__main__":
    check()
