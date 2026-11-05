"""Real configured DB locks and actual session files on isolated identities."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Event
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.knowledge.generations import generation_store, StaleGeneration  # noqa: E402
from app.memory.session_store import SessionStore  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402


def main():
    # Reuse the reserved standalone cleanup-probe identity convention.
    user = "reflection-cleanup-qa-" + uuid.uuid4().hex
    other = user + "-other"
    first, second = SessionStore(), SessionStore()
    entered, release, deleting = Event(), Event(), Event()
    try:
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
        for who in (user, other):
            generation_store.tombstone(who)
            second.delete_user(who)
            assert not Path(second._get_file_path(who)).exists()
        remove_probe_users(user, other)
    print("PASS: session manifest fence, delivery replay, concurrent updates and cleanup on", settings.auxiliary_store_backend)


if __name__ == "__main__":
    main()
