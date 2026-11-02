"""Real Redis atomic reflection counter and delivery replay acceptance.

Uses exact unique QA users/keys; never changes a production stream or setting.
"""
import concurrent.futures
from contextlib import contextmanager
from hashlib import sha256
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.memory.reflection_scheduler import ReflectionScheduler  # noqa: E402
from app.knowledge.generations import generation_store, StaleGeneration  # noqa: E402
from app.memory.session_scope import tombstone_session  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402


def check():
    user = "reflection-delivery-qa-" + uuid.uuid4().hex
    other = user + "-other"
    first, second = ReflectionScheduler(), ReflectionScheduler()
    client = first._redis
    scopes = [(user, "session", "turn"), (user, "other-session", "turn"),
              (user, "session", "other-turn"), (other, "session", "turn"),
              (user, "repair", "new-turn"), (user, "rollback", "pending-turn")]
    keys = [first._counter_key(user), first._counter_key(other)]
    keys.extend(first._delivery_key(*scope) for scope in scopes)
    try:
        # Different instances race on one logical delivery, including after a
        # response was lost. Only one increment can take effect.
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda i: (first if i % 2 else second).record_session(*scopes[0]), range(32)))
        assert results == [1] * 32
        counter, marker = keys[0], first._delivery_key(*scopes[0])
        assert 0 < client.ttl(counter) <= 604800
        assert client.exists(marker) == 0
        receipts = generation_store.snapshot(user)["reflection_deliveries"]
        assert receipts[sha256(b"session").hexdigest()][marker.rsplit(":", 1)[1]] is True
        assert first.record_session(*scopes[1]) == 2
        assert first.record_session(*scopes[2]) == 3
        assert first.record_session(*scopes[3]) == 1
        # Consumed work must not be resurrected by a replay or new process.
        client.delete(counter)
        assert ReflectionScheduler().record_session(*scopes[0]) == 0
        assert not client.exists(counter)
        # Repair a legacy non-expiring counter in the same atomic operation.
        client.set(counter, 2)
        assert first.record_session(*scopes[4]) == 3
        assert 0 < client.ttl(counter) <= 604800
        # Preserve an existing retention deadline; retries must not extend it.
        client.expire(counter, 60)
        assert second.record_session(*scopes[0]) == 3
        assert 0 < client.ttl(counter) <= 60
        assert client.exists(marker) == 0

        locked = generation_store.locked

        @contextmanager
        def failed_commit(who):
            with locked(who) as state:
                yield state
                raise RuntimeError("QA SQL commit failure")

        # Redis really writes; only the SQL commit fails and rolls back. The
        # handoff marker must remain non-expiring until the receipt commits.
        with patch.object(generation_store, "locked", failed_commit):
            try:
                first.record_session(*scopes[5])
            except RuntimeError as error:
                assert str(error) == "QA SQL commit failure"
            else:
                raise AssertionError("SQL commit failure was ignored")
        pending = first._delivery_key(*scopes[5])
        assert client.get(counter) == "4" and client.ttl(pending) == -1
        assert sha256(b"rollback").hexdigest() not in generation_store.snapshot(user)["reflection_deliveries"]
        # Upgrade a preexisting expiring marker and fail SQL once more.
        client.expire(pending, 45)
        with patch.object(generation_store, "locked", failed_commit):
            try:
                first.record_session(*scopes[5])
            except RuntimeError:
                pass
            else:
                raise AssertionError("SQL commit failure was ignored")
        assert client.get(counter) == "4" and client.ttl(pending) == -1
        client.delete(counter)
        assert second.record_session(*scopes[5]) == 0
        assert client.exists(counter, pending) == 0

        # A fresh interpreter must consult SQL even with no Redis markers.
        with tempfile.TemporaryDirectory(prefix="reflection-delivery-cold-") as folder:
            env = dict(os.environ, QDRANT_PATH=str(Path(folder) / "qdrant"),
                       CHROMA_PATH=str(Path(folder) / "legacy"))
            subprocess.run([sys.executable, "-c",
                            "import sys; from app.memory.reflection_scheduler import ReflectionScheduler; "
                            "assert ReflectionScheduler().record_session(*sys.argv[1:]) == 0",
                            *scopes[0]], check=True, env=env)
        assert not client.exists(counter)

        # Corruption fails before a Redis increment; it is never treated as an
        # empty receipt ledger. Restore only this unique synthetic user's data.
        saved = generation_store.snapshot(user)["reflection_deliveries"]
        with generation_store.locked(user) as state:
            state["reflection_deliveries"] = []
        try:
            try:
                first.record_session(user, "corrupt", "new")
            except ValueError:
                pass
            else:
                raise AssertionError("Corrupt receipts were silently discarded")
            assert not client.exists(counter, first._delivery_key(user, "corrupt", "new"))
        finally:
            with generation_store.locked(user) as state:
                state["reflection_deliveries"] = saved
        tombstone_session(user, "session")
        assert sha256(b"session").hexdigest() not in generation_store.snapshot(user)["reflection_deliveries"]
        try:
            first.record_session(*scopes[0])
        except StaleGeneration:
            pass
        else:
            raise AssertionError("Deleted session accepted a delivery")
        assert second.record_session(*scopes[1]) == 0
        first.delete_user(user)
        assert "reflection_deliveries" not in generation_store.snapshot(user)
        try:
            first.record_session(*scopes[1])
        except StaleGeneration:
            pass
        else:
            raise AssertionError("Deleted account accepted a delivery")
        assert second.record_session(*scopes[3]) == 1
        print(json.dumps({"real_redis": True, "concurrent_replay": "passed",
                          "tenant_session_turn_isolation": "passed", "consumed_replay": "passed",
                          "atomic_ttl_and_legacy_repair": "passed", "retention_preserved": "passed",
                          "sql_rollback_and_upgrade": "passed", "cold_process_replay": "passed",
                          "corrupt_receipts_rejected": "passed", "deleted_scope_fenced": "passed"}))
    finally:
        first.delete_user(user)
        first.delete_user(other)
        client.delete(*keys)
        assert not client.exists(*keys)
        remove_probe_users(user, other)


if __name__ == "__main__":
    check()
