"""Actual Qdrant/DB deletion races on isolated, explicitly supplied QA users.

Only the standalone client process pauses a provider result; application source
and service processes are untouched. Embeddings use the configured provider.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Event
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.knowledge.generations import generation_store, StaleGeneration  # noqa: E402
import app.memory.memory_store as module  # noqa: E402
from app.memory.memory_store import memory_store as store  # noqa: E402
from app.memory.version_store import memory_version_store as versions  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402

CONTENT = 'Memory fence QA: inspect source evidence before taking study notes.'


def identity(user):
    return 'mem_fence_qa_' + user


def seed(users):
    for user in users:
        assert not generation_store.snapshot(user).get('deleted')
        store.restore_memory(identity(user), CONTENT, {'user_id': user, 'category': 'preference',
                             'topic': 'Memory fence QA', 'importance': 0.5, 'evidence_hashes': '[]'})
        versions.snapshot(store.get_memory(identity(user)), 'qa_seed')
        assert store.count_user_memories(user) == versions.count_user(user) == 1


def erase(user):
    generation_store.tombstone(user)
    store.delete_user_memories(user)
    versions.delete_user(user)
    assert store.count_user_memories(user) == versions.count_user(user) == 0


def verify(user):
    assert generation_store.snapshot(user).get('deleted'), 'Missing persisted fence'
    old = {'id': identity(user), 'user_id': user, 'content': CONTENT, 'category': 'preference'}
    calls = [lambda: store.add_memory(user, 'preference', CONTENT),
             lambda: store.restore_memory(identity(user), CONTENT, old),
             lambda: versions.snapshot(old, 'late')]
    for call in calls:
        try:
            call()
        except StaleGeneration:
            pass
        else:
            raise AssertionError('Deleted memory or version accepted a late write')
    assert store.update_memory(identity(user), CONTENT) is False
    assert store.set_frozen(identity(user), True) is False
    assert store.update_metadata(identity(user), {'status': 'active'}) is False
    assert store.count_user_memories(user) == versions.count_user(user) == 0


def provider_race(user, operation):
    entered, release = Event(), Event()
    original = module.embeddings
    old = store.get_memory(identity(user))

    class Paused:
        def profile(self):
            return original.profile()

        def __call__(self, texts):
            vectors = original(texts)
            entered.set()
            assert release.wait(15), 'QA provider release timeout'
            return vectors

    calls = {'add': lambda: store.add_memory(user, 'preference', CONTENT),
             'restore': lambda: store.restore_memory(identity(user), CONTENT, old, snapshot_current=True),
             'update': lambda: store.update_memory(identity(user), CONTENT)}
    with patch.object(module, 'embeddings', Paused()), ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(calls[operation])
        try:
            assert entered.wait(45), 'Configured embedding call failed or timed out'
            deleting = pool.submit(erase, user)
            deleting.result(10)  # Provider waiting must not prevent account deletion.
        finally:
            release.set()
        if operation == 'update':
            assert writing.result(15) is False
        else:
            try:
                writing.result(15)
            except StaleGeneration:
                pass
            else:
                raise AssertionError('In-flight provider result resurrected deleted memory')
    verify(user)


def concurrent_versions(user):
    memory = store.get_memory(identity(user))
    base = versions.count_user(user)
    with ThreadPoolExecutor(max_workers=8) as pool:
        allocated = list(pool.map(lambda _: versions.snapshot(memory, 'qa_concurrent'), range(32)))
    assert sorted(allocated) == list(range(base + 1, base + 33))
    assert versions.count_user(user) == base + 32
    # Real concurrent metadata updates must preserve unrelated fields.
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(store.update_importance, identity(user), 0.9)
        two = pool.submit(store.update_memory_topic, identity(user), 'Memory fence QA updated')
        assert one.result(15) and two.result(15)
    current = store.get_memory(identity(user))
    assert current['importance'] == 0.9 and current['topic'] == 'Memory fence QA updated'


def main():
    mode, *users = sys.argv[1:]
    if mode == 'selftest' and not users:
        user = 'reflection-cleanup-qa-' + uuid.uuid4().hex
        users = [user, user + '-other', user + ':nested', user + '*?[old]']
        try:
            seed(users)
            concurrent_versions(users[3])
            for who, operation in zip(users, ['add', 'restore', 'update']):
                provider_race(who, operation)
            assert store.count_user_memories(users[3]) == 1
        finally:
            for who in users:
                erase(who)
                verify(who)
            remove_probe_users(*users)
    else:
        if (len(users) != 3 or len(set(users)) != 3
                or any(not user.isascii() or not user.isdecimal() or len(user) > 20 for user in users)):
            raise ValueError('Requires three isolated registered QA user IDs')
        if mode == 'seed':
            seed(users)
        elif mode == 'race':
            provider_race(users[0], 'add')
            provider_race(users[1], 'restore')
            concurrent_versions(users[2])
            assert store.count_user_memories(users[2]) == 1
        elif mode == 'verify':
            for user in users:
                verify(user)
        else:
            raise ValueError('Unknown operation')
    print('PASS: memory fence', mode, 'on', settings.auxiliary_store_backend)


if __name__ == '__main__':
    main()
