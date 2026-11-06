"""Real configured DB locks and actual session files on isolated identities."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import contextmanager
from datetime import timedelta
import sys
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.knowledge.generations import generation_store, StaleGeneration  # noqa: E402
from app.memory.session_store import SessionStore  # noqa: E402
from app.memory.short_term_memory import ShortTermMemoryManager  # noqa: E402
from app.memory.session_persistence import session_persistence  # noqa: E402
from app.memory.session_history import session_key  # noqa: E402
from app.memory.session_retention import SessionHistoryRetention  # noqa: E402
from app.memory.completion_retention import require_current  # noqa: E402
from app.core.time import utc_now  # noqa: E402
from app.models.chat import Message  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402


def verify_history(user):
    """Actual configured SQLite/MySQL commits, including lost acknowledgments."""
    managers = [ShortTermMemoryManager(), ShortTermMemoryManager()]
    message = Message(role="user", content="isolated QA", timestamp="2026-11-06T00:00:00Z")
    with patch.object(session_persistence, "_ensure_connection", return_value=False):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: managers[i % 2].add_message(
                "history", message, user_id=user, delivery_id="same-turn"), range(48)))
        assert ShortTermMemoryManager().get_history("history", user_id=user) == [message]
        original = generation_store.locked
        for stage in ("rollback", "lost_ack"):
            @contextmanager
            def fail(who):
                with original(who) as state:
                    yield state
                    if stage == "rollback":
                        raise OSError("QA rollback")
                raise OSError("QA acknowledgment lost")
            with patch.object(generation_store, "locked", fail):
                try:
                    managers[0].add_message(stage, message, user_id=user, delivery_id=stage)
                except OSError:
                    pass
                else:
                    raise AssertionError("Injected failure was not reached")
            assert len(ShortTermMemoryManager().get_history(stage, user_id=user)) == (stage == "lost_ack")
            managers[1].add_message(stage, message, user_id=user, delivery_id=stage)
            assert ShortTermMemoryManager().get_history(stage, user_id=user) == [message]


def verify_retention(prefix):
    """Use actual keyset SQL and account locks, restricted to QA identities."""
    users = [prefix + "-a", prefix + "-b"]
    with patch.object(session_persistence, "_ensure_connection", return_value=False):
        manager = ShortTermMemoryManager()
        message = Message(role="user", content="retention QA", timestamp=utc_now().isoformat())
        for user in users:
            for session in ("unread", "active"):
                manager.add_message(session, message, user_id=user, delivery_id="receipt")
            with generation_store.locked(user) as state:
                state["session_histories"][session_key("unread")]["expires_at"] = (utc_now() - timedelta(seconds=1)).timestamp()
                old = utc_now() - timedelta(days=max(settings.memory_completion_retention_days,
                                                      settings.memory_version_retention_days) + 1)
                base = {"fingerprint": "f" * 64, "created_at": old.isoformat(), "phases": {"history": True}}
                state["memory_completions"] = {"qa": {
                    "expired": {**base, "reference_time": old.isoformat()},
                    "active": {**base, "reference_time": utc_now().isoformat()},
                    "legacy": dict(base),
                }}
        before = {user: generation_store.snapshot(user) for user in users}
        def page(after=None, *, limit=100):
            rows = generation_store.user_page(prefix if after is None else after, limit=limit)
            return [user for user in rows if user in users]
        scoped = SimpleNamespace(user_page=page, locked=generation_store.locked)
        workers = [SessionHistoryRetention(scoped, batch_size=1) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda w: w.run_batch(), workers))
        assert sum(row["expired"] for row in results) == 2
        assert sum(row["failed"] for row in results) == 0
        assert workers[0].run_batch()["expired"] == 2
        assert workers[0].run_batch()["scanned"] == 0
        for user in users:
            after = generation_store.snapshot(user)
            assert after["session_histories"][session_key("unread")] == {"expired": True}
            assert after["session_histories"][session_key("active")] == before[user]["session_histories"][session_key("active")]
            assert set(after["memory_completions"]["qa"]) == {"active", "legacy"}
            for key in ("active", "legacy"):
                assert after["memory_completions"]["qa"][key] == before[user]["memory_completions"]["qa"][key]
            require_current(after, after["memory_completions"]["qa"]["active"]["reference_time"])
            try:
                require_current(after, before[user]["memory_completions"]["qa"]["expired"]["reference_time"])
            except ValueError:
                pass
            else:
                raise AssertionError("Expired completion was accepted")
            assert manager.get_history("unread", user_id=user) == []
    return users


def main():
    # Reuse the reserved standalone cleanup-probe identity convention.
    user = "reflection-cleanup-qa-" + uuid.uuid4().hex
    other = user + "-other"
    retention_users = [user + "-retention-a", user + "-retention-b"]
    first, second = SessionStore(), SessionStore()
    entered, release, deleting = Event(), Event(), Event()
    try:
        verify_history(other)
        assert verify_retention(user + "-retention") == retention_users
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: (first, second)[i % 2].register_session(other, str(i)), range(32)))
            list(pool.map(lambda i: (first, second)[i % 2].increment_message_count(other, "0"), range(32)))
        assert len(first.cleanup_session_ids(other)) == 32
        assert next(row for row in first.get_sessions(other) if row["id"] == "0")["message_count"] == 33
        def deliver(i):
            store = (first, second)[i % 2]
            store.register_session(other, "0", delivery_id=str(i % 8))
            store.increment_message_count(other, "0", delivery_id=str(i % 8))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(deliver, range(64)))
        assert next(row for row in first.get_sessions(other) if row["id"] == "0")["message_count"] == 49
        before = Path(first._get_file_path(other)).read_bytes()
        fresh_delivery = SessionStore()
        fresh_delivery.register_session(other, "0", delivery_id="0")
        fresh_delivery.increment_message_count(other, "0", delivery_id="0")
        assert Path(first._get_file_path(other)).read_bytes() == before
        original = first._write

        def delayed(*args):
            entered.set()
            assert release.wait(10)
            original(*args)

        def erase():
            deleting.set()
            generation_store.tombstone(user)
            assert second.cleanup_session_ids(user) == ["racing"]
            second.delete_user(user)

        with patch.object(first, "_write", delayed), ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(first.register_session, user, "racing")
            try:
                assert entered.wait(10)
                deletion = pool.submit(erase)
                assert deleting.wait(10) and not deletion.done()
            finally:
                release.set()
            writing.result(15)
            deletion.result(15)
        fresh = SessionStore()
        calls = [lambda: fresh.register_session(user, "late"), lambda: fresh._save(user, {"late": {}}),
                 lambda: fresh.update_title(user, "late", "late"),
                 lambda: fresh.increment_message_count(user, "late"), lambda: fresh.delete_session(user, "late")]
        for call in calls:
            try:
                call()
            except StaleGeneration:
                pass
            else:
                raise AssertionError("Deleted manifest was mutated")
        assert fresh.get_sessions(user) == [] and fresh.get_session_count(user) == 0
        assert not Path(fresh._get_file_path(user)).exists()
        assert len(fresh.cleanup_session_ids(other)) == 32
    finally:
        release.set()
        for who in (user, other, *retention_users):
            generation_store.tombstone(who)
            second.delete_user(who)
            assert not Path(second._get_file_path(who)).exists()
        remove_probe_users(user, other, *retention_users)
    print("PASS: session history delivery/retention, rollback, lost ACK, concurrent updates and cleanup on", settings.auxiliary_store_backend)


if __name__ == "__main__":
    main()
