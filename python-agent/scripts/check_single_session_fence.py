"""Actual Redis/DB single-session deletion races on isolated QA owners only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.chat import delete_session  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.knowledge.generations import generation_store, StaleGeneration  # noqa: E402
from app.memory.session_persistence import session_persistence as persistence  # noqa: E402
from app.memory.session_scope import tombstone_session, session_deleted  # noqa: E402
from app.memory.session_store import session_store as store  # noqa: E402
from app.memory.short_term_memory import ShortTermMemoryManager  # noqa: E402
from app.memory.working_memory import WorkingMemoryManager  # noqa: E402
from app.models.chat import Message  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402


def message(content="Single-session QA"):
    return Message(role="user", content=content, timestamp="2026-11-02T00:00:00Z", token_count=500)


def seed(user, target, keep):
    assert not generation_store.snapshot(user).get("deleted")
    short = ShortTermMemoryManager()
    for sid in (target, keep):
        store.register_session(user, sid)
        short.add_message(sid, message(), user_id=user)
        assert len(short.get_history(sid, user_id=user)) == 1


def verify(user, target, keep):
    state = generation_store.snapshot(user)
    assert session_deleted(state, target) and not state.get("deleted")
    assert not session_deleted(state, keep)
    assert target not in store.cleanup_session_ids(user)
    assert keep in store.cleanup_session_ids(user)
    assert persistence.count_sessions([target], user_id=user) == 0
    assert persistence.count_sessions([keep], user_id=user) == 1
    assert len(ShortTermMemoryManager().get_history(keep, user_id=user)) > 0
    for operation in (
        lambda: ShortTermMemoryManager().get_history(target, user_id=user),
        lambda: ShortTermMemoryManager().add_message(target, message("late"), user_id=user),
        lambda: WorkingMemoryManager().add_message(target, message("late"), user_id=user),
        lambda: persistence.save_messages(target, [message("late")], user_id=user),
        lambda: store.register_session(user, target),
        lambda: store.update_title(user, target, "late"),
        lambda: store.increment_message_count(user, target),
    ):
        try:
            operation()
        except StaleGeneration:
            pass
        else:
            raise AssertionError("Deleted session read or republished")
    # Verify with an independent interpreter, not only an existing cache object.
    code = """import sys
from app.memory.short_term_memory import ShortTermMemoryManager
from app.knowledge.generations import StaleGeneration
try: ShortTermMemoryManager().get_history(sys.argv[2],user_id=sys.argv[1])
except StaleGeneration: print('rejected')
else: raise AssertionError('Cold process read deleted session')
"""
    assert subprocess.check_output([sys.executable, "-c", code, user, target], text=True).strip().splitlines()[-1] == "rejected"


def selftest():
    user = "reflection-cleanup-qa-" + uuid.uuid4().hex
    other = user + "-other"
    target, keep = "single-session-qa-target", "single-session-qa-keep"
    entered, release, deleting = Event(), Event(), Event()
    try:
        seed(user, target, keep)
        seed(other, target, keep)
        short = ShortTermMemoryManager()
        working = WorkingMemoryManager()
        working.add_message(target, message(), user_id=user)
        original = persistence._redis.setex

        def paused(*args, **kwargs):
            entered.set()
            assert release.wait(15)
            return original(*args, **kwargs)

        def erase():
            deleting.set()
            tombstone_session(user, target)

        with patch.object(persistence._redis, "setex", paused), ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(short.add_message, target, message("racing"), user_id=user)
            try:
                assert entered.wait(15)
                deletion = pool.submit(erase)
                assert deleting.wait(10) and not deletion.done()
            finally:
                release.set()
            writing.result(20)
            deletion.result(20)
        # A permanent fence commits independently of later cleanup failure.
        with patch.object(persistence._redis, "delete", side_effect=OSError("QA offline")):
            try:
                asyncio.run(delete_session(target, user))
            except RuntimeError:
                pass
            else:
                raise AssertionError("Redis failure was reported as complete")
        assert target in store.cleanup_session_ids(user)
        assert session_deleted(generation_store.snapshot(user), target)
        persistence._available = True
        assert asyncio.run(delete_session(target, user)) == {"deleted": True, "session_id": target}
        assert asyncio.run(delete_session(target, user))["deleted"] is True
        verify(user, target, keep)
        try:
            working.get_messages(target, user_id=user)
        except StaleGeneration:
            pass
        else:
            raise AssertionError("Existing working cache read deleted session")
        assert len(ShortTermMemoryManager().get_history(target, user_id=other)) == 1
        assert not generation_store.snapshot(other).get("deleted")

        # The actual summary path must start its model call before deletion.
        for i in range(20):
            short.add_message(target, message(str(i)), user_id=other)
        entered.clear()
        release.clear()

        def model(_):
            entered.set()
            assert release.wait(15)
            return SimpleNamespace(content="late QA summary")

        with patch("app.memory.short_term_memory.llm", SimpleNamespace(invoke=model)), ThreadPoolExecutor(max_workers=1) as pool:
            summary = pool.submit(short.summarize, target, user_id=other)
            try:
                assert entered.wait(15)
                asyncio.run(delete_session(target, other))
            finally:
                release.set()
            try:
                summary.result(20)
            except StaleGeneration:
                pass
            else:
                raise AssertionError("Summary published after deletion")
        verify(other, target, keep)
    finally:
        for who in (user, other):
            generation_store.tombstone(who)
            persistence.delete_user_sessions(who)
            store.delete_user(who)
        remove_probe_users(user, other)


def main():
    mode, *args = sys.argv[1:]
    if mode == "selftest" and not args:
        selftest()
    else:
        if len(args) != 3 or len(set(args[1:])) != 2 or any(
            not value.isascii() or not value.isdecimal() or len(value) > 20 for value in args
        ):
            raise ValueError("Requires isolated registered QA owner and two canonical session IDs")
        if mode == "seed":
            seed(*args)
        elif mode == "verify":
            verify(*args)
        else:
            raise ValueError("Unknown operation")
    print("PASS: single-session deletion fence", mode, "on", settings.auxiliary_store_backend)


if __name__ == "__main__":
    main()
