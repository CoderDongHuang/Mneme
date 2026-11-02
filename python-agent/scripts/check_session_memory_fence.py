"""Actual Redis/DB cache races on reserved QA owners, never provider calls."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.knowledge.generations import generation_store, StaleGeneration  # noqa: E402
from app.memory.session_persistence import session_persistence as persistence  # noqa: E402
from app.memory.short_term_memory import ShortTermMemoryManager  # noqa: E402
from app.memory.working_memory import WorkingMemoryManager  # noqa: E402
from app.models.chat import Message  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402

SID = "session-memory-qa-shared"


def message(content="Session cache QA history"):
    return Message(role="user", content=content, timestamp="2026-11-02T00:00:00Z", token_count=500)


def fresh_read(user):
    code = "from app.memory.short_term_memory import ShortTermMemoryManager; import sys; print(len(ShortTermMemoryManager().get_history(sys.argv[2],user_id=sys.argv[1])))"
    return int(subprocess.check_output([sys.executable, "-c", code, user, SID], text=True).strip().splitlines()[-1])


def seed(users):
    assert persistence._ensure_connection()
    first, second = ShortTermMemoryManager(), ShortTermMemoryManager()
    for user in users:
        assert not generation_store.snapshot(user).get("deleted")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: (first, second)[i % 2].add_message(SID, message(str(i)), user_id=user), range(20)))
        assert {m.content for m in first.get_history(SID, user_id=user)} == {str(i) for i in range(20)}
        assert fresh_read(user) == 20
    assert persistence._session_key(SID, users[0]) != persistence._session_key(SID, users[1])


def race(users):
    user, other = users
    short, working = ShortTermMemoryManager(), WorkingMemoryManager()
    working.add_message(SID, message(), user_id=user)
    working.add_message(SID, message("Protected QA"), user_id=other)
    assert working.get_all_sessions(other)[0]["title"] == "Protected QA"
    entered, release, deleting = Event(), Event(), Event()
    original = persistence._redis.setex

    def paused(*args, **kw):
        entered.set()
        assert release.wait(15)
        return original(*args, **kw)

    def erase():
        deleting.set()
        generation_store.tombstone(user)

    with patch.object(persistence._redis, "setex", paused), ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(short.add_message, SID, message("racing write"), user_id=user)
        try:
            assert entered.wait(15)
            deletion = pool.submit(erase)
            assert deleting.wait(10) and not deletion.done()
        finally:
            release.set()
        writing.result(20)
        deletion.result(20)
    for operation in [lambda: short.get_history(SID, user_id=user),
                      lambda: working.add_message(SID, message(), user_id=user),
                      lambda: working.get_messages(SID, user_id=user),
                      lambda: persistence.save_messages(SID, [message()], user_id=user)]:
        try:
            operation()
        except StaleGeneration:
            pass
        else:
            raise AssertionError("Deleted cache was read or republished")
    # A model result started before a newer turn must not overwrite it.
    entered.clear()
    release.clear()

    def model(_):
        entered.set()
        assert release.wait(15)
        return SimpleNamespace(content="Stale QA summary")

    with patch("app.memory.short_term_memory.llm", SimpleNamespace(invoke=model)), ThreadPoolExecutor(max_workers=1) as pool:
        summary = pool.submit(short.summarize, SID, user_id=other)
        try:
            assert entered.wait(15)
            ShortTermMemoryManager().add_message(SID, message("newer turn"), user_id=other)
        finally:
            release.set()
        summary.result(20)
    assert len(short.get_history(SID, user_id=other)) == 21
    assert fresh_read(other) == 21
    # A cold process cannot recover a tombstoned user's Redis history.
    code = """from app.memory.short_term_memory import ShortTermMemoryManager
from app.knowledge.generations import StaleGeneration
import sys
try: ShortTermMemoryManager().get_history(sys.argv[2],user_id=sys.argv[1])
except StaleGeneration: print('rejected')
else: raise AssertionError('Cold process read deleted history')
"""
    assert subprocess.check_output([sys.executable, "-c", code, user, SID], text=True).strip().splitlines()[-1] == "rejected"


def verify(users):
    for user in users:
        assert generation_store.snapshot(user).get("deleted")
        assert persistence.count_sessions([SID], user_id=user) == 0
        assert not list(persistence._redis.scan_iter(match=persistence._user_prefix(user) + "*"))
        try:
            persistence.save_messages(SID, [message("late")], user_id=user)
        except StaleGeneration:
            pass
        else:
            raise AssertionError("Late Redis write was accepted")


def main():
    mode, *users = sys.argv[1:]
    if mode == "selftest" and not users:
        user = "reflection-cleanup-qa-" + uuid.uuid4().hex
        users = [user, user + "-other"]
        try:
            seed(users)
            race(users)
        finally:
            for who in users:
                generation_store.tombstone(who)
                persistence.delete_user_sessions(who)
            verify(users)
            remove_probe_users(*users)
    else:
        if (not 1 <= len(users) <= 2 or len(set(users)) != len(users)
                or any(not user.isascii() or not user.isdecimal() or len(user) > 20 for user in users)):
            raise ValueError("Requires isolated registered QA user IDs")
        if mode in {"seed", "race"} and len(users) != 2:
            raise ValueError("Requires two separate QA owners")
        if mode == "seed":
            seed(users)
        elif mode == "race":
            race(users)
        elif mode == "verify":
            verify(users)
        else:
            raise ValueError("Unknown operation")
    print("PASS: session memory fence", mode, "on", settings.auxiliary_store_backend)


if __name__ == "__main__":
    main()
