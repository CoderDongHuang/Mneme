"""Actual storage regression for registered QA accounts supplied by the E2E.

No provider, production monkeypatch, DDL or manual account deletion. Tombstones
are intentional; callers must delete these accounts through the normal API.
"""
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.trace_store import agent_trace_store as trace  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.privacy import privacy_store as policy, require_cloud_processing  # noqa: E402
from app.knowledge.generations import generation_store, StaleGeneration  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402


def race(user, kind):
    target, name = (trace, "_insert_record") if kind == "trace" else (policy, "_save")
    original = getattr(target, name)
    entered, release, deleting = Event(), Event(), Event()

    def delayed(*args):
        entered.set()
        assert release.wait(10), "Storage release timed out"
        return original(*args)

    def erase():
        deleting.set()
        generation_store.tombstone(user)
        trace.delete_user(user)
        policy.delete(user)

    with patch.object(target, name, delayed), ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(trace.record, user, "fence-qa", "fence-qa", "ok") if kind == "trace" else pool.submit(policy.save, user, True, 1)
        try:
            assert entered.wait(10), "Storage writer did not enter"
            deletion = pool.submit(erase)
            assert deleting.wait(10), "Deletion did not start"
            assert not deletion.done(), "Deletion bypassed active storage writer"
        finally:
            release.set()
        writing.result(15)
        deletion.result(15)
    verify(user)


def verify(user):
    assert generation_store.snapshot(user).get("deleted"), "Missing account tombstone"
    trace.record(user, "fence-qa", "late", "ok")
    try:
        policy.save(user, True, 1)
    except StaleGeneration:
        pass
    else:
        raise AssertionError("Deleted account saved a policy")
    try:
        require_cloud_processing(user)
    except StaleGeneration:
        pass
    else:
        raise AssertionError("Deleted account regained default cloud consent")
    assert trace.count_user(user) == policy.count_user(user) == 0, "Deleted data reappeared"


def main():
    mode, *users = sys.argv[1:]
    if mode == "selftest" and not users:
        user = "reflection-cleanup-qa-" + uuid.uuid4().hex
        isolated = [user, user + "-other", user + ":nested"]
        try:
            seed(isolated)
            race(isolated[0], "trace")
            race(isolated[1], "privacy")
            require_cloud_processing(isolated[2])
            assert policy.count_user(isolated[2]) == 1 and trace.count_user(isolated[2]) >= 1
        finally:
            for who in isolated:
                generation_store.tombstone(who)
                trace.delete_user(who)
                policy.delete(who)
                verify(who)
            remove_probe_users(*isolated)
        print("PASS: trace/privacy selftest on", settings.auxiliary_store_backend)
        return
    if settings.auxiliary_store_backend not in {"sqlite", "mysql"} or len(users) != 3 or len(set(users)) != 3:
        raise ValueError("Requires a supported actual store and three isolated registered QA accounts")
    if any(not user.isascii() or not user.isdecimal() or len(user) > 20 for user in users):
        raise ValueError("Invalid QA user identity")
    if mode == "seed":
        seed(users)
    elif mode == "race":
        race(users[0], "trace")
        race(users[1], "privacy")
        assert policy.count_user(users[2]) == 1 and trace.count_user(users[2]) >= 1
        require_cloud_processing(users[2])
    elif mode == "verify":
        for user in users:
            verify(user)
    else:
        raise ValueError("Unknown operation")
    print("PASS: trace/privacy", mode, "on actual shared storage")


def seed(users):
    for user in users:
        policy.save(user, True, 1)
        trace.record(user, "fence-qa", "fence-qa", "ok")
        assert policy.count_user(user) == 1 and trace.count_user(user) >= 1


if __name__ == "__main__":
    main()
