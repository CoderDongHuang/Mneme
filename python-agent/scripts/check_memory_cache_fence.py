"""Actual storage/cache races in a standalone process using isolated QA owners."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Event
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.knowledge.generations import generation_store, StaleGeneration  # noqa: E402
from app.memory.cache_revision import memory_cache_revision as revision  # noqa: E402
from app.memory.long_term_memory import LongTermMemoryManager  # noqa: E402
from app.memory.memory_store import memory_store as store  # noqa: E402
from app.memory.version_store import memory_version_store as versions  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402

CONTENT = 'Memory cache QA: use spaced practice and inspect source evidence.'
UPDATED = 'Memory cache QA: updated source evidence retained for the other account.'


def identity(user):
    return 'mem_cache_qa_' + user


def seed(users):
    for user in users:
        assert not generation_store.snapshot(user).get('deleted')
        store.restore_memory(identity(user), CONTENT, {'user_id': user, 'category': 'preference',
                             'topic': 'Memory cache QA', 'importance': 0.5, 'evidence_hashes': '[]'})
        revision.bump(user)
        assert store.count_user_memories(user) == 1


def erase(user):
    generation_store.tombstone(user)
    store.delete_user_memories(user)
    versions.delete_user(user)
    LongTermMemoryManager()._invalidate_cache(user)


def verify(user):
    assert generation_store.snapshot(user).get('deleted')
    manager = LongTermMemoryManager()
    for call in [lambda: manager.get_preferences(user),
                 lambda: manager.get_weak_points(user),
                 lambda: manager.get_progress(user),
                 lambda: manager._set_cache(user, 'preferences', [{'content': CONTENT}], 0),
                 lambda: revision.current(user)]:
        try:
            call()
        except StaleGeneration:
            pass
        else:
            raise AssertionError('Deleted account cache was read or republished')
    assert revision.bump(user) == 0
    assert not revision._redis.exists(revision._key(user))
    assert not manager._cache
    assert store.count_user_memories(user) == versions.count_user(user) == 0


def race(users):
    deleted, other = users
    first, second, cold = (LongTermMemoryManager() for _ in range(3))
    assert first.get_preferences(deleted)[0]['content'] == CONTENT
    assert second.get_preferences(other)[0]['content'] == CONTENT
    revision._redis.set(revision._key(deleted), '100', ex=300)
    revision._redis.set(revision._key(other), '200', ex=300)
    original = store.get_by_category
    entered, release = Event(), Event()

    def paused(user, *args, **kwargs):
        result = original(user, *args, **kwargs)
        if user == deleted:
            entered.set()
            assert release.wait(15)
        return result

    with patch.object(store, 'get_by_category', paused), ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(cold.get_preferences, deleted)
        try:
            assert entered.wait(45)
            pool.submit(erase, deleted).result(10)
        finally:
            release.set()
        try:
            reading.result(15)
        except StaleGeneration:
            pass
        else:
            raise AssertionError('Late storage result was republished')
    try:
        first.get_preferences(deleted)
    except StaleGeneration:
        pass
    else:
        raise AssertionError('Another replica served its old cache after deletion')
    assert deleted not in first._cache and deleted not in cold._cache
    assert second.get_preferences(other)[0]['content'] == CONTENT
    assert revision._redis.get(revision._key(other)) == '200'

    # An old query must not be labeled with the newer invalidation revision.
    second._cache.clear()
    entered.clear()
    release.clear()

    def paused_other(user, *args, **kwargs):
        result = original(user, *args, **kwargs)
        if not entered.is_set():
            entered.set()
            assert release.wait(15)
        return result

    with patch.object(store, 'get_by_category', paused_other), ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(second.get_preferences, other)
        try:
            assert entered.wait(45)
            assert store.update_memory(identity(other), UPDATED)
            first._invalidate_cache(other)
        finally:
            release.set()
        assert reading.result(15)[0]['content'] == UPDATED
    assert second.get_preferences(other)[0]['content'] == UPDATED
    # A new process observes the committed revision, without Redis INCR/GET.
    expected = revision.current(other)
    code = 'from app.memory.cache_revision import memory_cache_revision as r; import sys; print(r.current(sys.argv[1]))'
    assert subprocess.check_output([sys.executable, '-c', code, other], text=True).strip() == str(expected)
    verify(deleted)


def main():
    mode, *users = sys.argv[1:]
    if mode == 'selftest' and not users:
        user = 'reflection-cleanup-qa-' + uuid.uuid4().hex
        users = [user, user + '-other']
        try:
            seed(users)
            race(users)
        finally:
            for who in users:
                erase(who)
                verify(who)
            remove_probe_users(*users)
    else:
        if (len(users) != 2 or len(set(users)) != 2
                or any(not user.isascii() or not user.isdecimal() or len(user) > 20 for user in users)):
            raise ValueError('Requires two isolated registered QA user IDs')
        if mode == 'seed':
            seed(users)
        elif mode == 'race':
            race(users)
        elif mode == 'verify':
            for user in users:
                verify(user)
        else:
            raise ValueError('Unknown operation')
    print('PASS: memory cache fence', mode, 'on', settings.auxiliary_store_backend)


if __name__ == '__main__':
    main()
