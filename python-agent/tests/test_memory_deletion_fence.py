"""Persistent account fences and real local Qdrant/SQLite memory races."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local
import uuid

import pytest

import app.memory.memory_store as module
from app.knowledge.generations import generation_store, StaleGeneration
from app.memory.memory_store import MemoryVectorStore, memory_store
from app.memory.version_store import MemoryVersionStore
from app.utils.embedding import embeddings


@pytest.fixture
def stores(tmp_path, monkeypatch):
    versions = MemoryVersionStore(str(tmp_path / 'versions.sqlite3'))
    monkeypatch.setattr(module, 'memory_version_store', versions)
    store = object.__new__(MemoryVectorStore)
    name = 'memory-fence-' + uuid.uuid4().hex
    store._collection = memory_store._client.get_or_create_collection(
        name, metadata={'embedding_profile': embeddings.profile()}, embedding_function=embeddings)
    try:
        yield store, versions
    finally:
        memory_store._client.delete_collection(name)


@pytest.mark.parametrize('operation', ['add', 'update', 'restore'])
def test_provider_inflight_cannot_resurrect_deleted_memory(stores, monkeypatch, operation):
    store, versions = stores
    mem_id = store.add_memory('user', 'preference', 'original')
    original = store.get_memory(mem_id)
    entered, release = Event(), Event()

    def delayed(texts):
        entered.set()
        assert release.wait(5)
        return embeddings(texts)

    monkeypatch.setattr(module, 'embeddings', type('Embedding', (), {
        '__call__': lambda self, texts: delayed(texts), 'profile': lambda self: embeddings.profile()})())
    calls = {'add': lambda: store.add_memory('user', 'preference', 'late'),
             'update': lambda: store.update_memory(mem_id, 'late'),
             'restore': lambda: store.restore_memory(mem_id, 'late', original)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(calls[operation])
        try:
            assert entered.wait(5)
            generation_store.tombstone('user')
            store.delete_user_memories('user')
            versions.delete_user('user')
            assert store.count_user_memories('user') == versions.count_user('user') == 0
        finally:
            release.set()
        if operation == 'update':
            assert writing.result(5) is False
        else:
            with pytest.raises(StaleGeneration):
                writing.result(5)
    assert store.count_user_memories('user') == versions.count_user('user') == 0


def test_all_existing_record_mutations_and_snapshot_rejected_after_tombstone(stores):
    store, versions = stores
    mem_id = store.add_memory('user', 'preference', 'original')
    old = store.get_memory(mem_id)
    other = store.add_memory('other', 'preference', 'kept')
    generation_store.tombstone('user')
    calls = [lambda: store.update_importance(mem_id, 1), lambda: store.update_memory_topic(mem_id, 'late'),
             lambda: store.update_memory(mem_id, topic='late'), lambda: store.set_frozen(mem_id, True),
             lambda: store.update_metadata(mem_id, {'status': 'ignored'}), lambda: store.delete_memory(mem_id),
             lambda: versions.snapshot(old, 'late')]
    for call in calls:
        with pytest.raises(StaleGeneration):
            call()
    assert store.get_memory(mem_id) == old
    assert versions.count_user('user') == 0
    store.delete_user_memories('user')
    versions.delete_user('user')
    assert store.count_user_memories('user') == versions.count_user('user') == 0
    assert store.get_memory(other)['content'] == 'kept'


def test_concurrent_metadata_reread_preserves_both_fields_and_ordered_snapshots(stores, monkeypatch):
    store, versions = stores
    mem_id = store.add_memory('user', 'preference', 'original')
    original, seen, barrier = store.get_memory, local(), Barrier(2)

    def first_read(mid):
        result = original(mid)
        if not getattr(seen, 'read', False):
            seen.read = True
            barrier.wait(5)
        return result

    with monkeypatch.context() as fault:
        fault.setattr(store, 'get_memory', first_read)
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(store.update_importance, mem_id, 0.9)
            two = pool.submit(store.update_memory_topic, mem_id, 'new topic')
            assert one.result(10) and two.result(10)
    result = store.get_memory(mem_id)
    assert result['importance'] == 0.9 and result['topic'] == 'new topic'
    history = versions.list_versions('user', mem_id)
    assert [item['version'] for item in history] == [2, 1]
    assert history[0]['metadata']['importance'] == 0.9 or history[0]['metadata']['topic'] == 'new topic'
    assert history[1]['metadata']['importance'] == 0.5 and history[1]['metadata']['topic'] == ''


def test_storage_write_drains_before_tombstone_and_cleanup(stores, monkeypatch):
    store, versions = stores
    entered, release, deleting = Event(), Event(), Event()
    original = store._collection.add

    def delayed(**kwargs):
        entered.set()
        assert release.wait(5)
        original(**kwargs)

    def erase():
        deleting.set()
        generation_store.tombstone('user')
        store.delete_user_memories('user')
        versions.delete_user('user')

    monkeypatch.setattr(store._collection, 'add', delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(store.add_memory, 'user', 'preference', 'original')
        try:
            assert entered.wait(5)
            deletion = pool.submit(erase)
            assert deleting.wait(5) and not deletion.done()
        finally:
            release.set()
        writing.result(10)
        deletion.result(10)
    assert store.count_user_memories('user') == versions.count_user('user') == 0


def test_two_version_store_instances_allocate_unique_concurrent_versions(stores):
    _, one = stores
    two = MemoryVersionStore(str(one.path))
    memory = {'id': 'm1', 'user_id': 'user', 'content': 'original'}
    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = list(pool.map(lambda index: (one, two)[index % 2].snapshot(memory, 'edit'), range(32)))
    assert sorted(versions) == list(range(1, 33))
    assert one.count_user('user') == 32


@pytest.mark.parametrize('kind', ['vector', 'version'])
def test_silent_delete_is_detected_and_retry_cleans_only_target(stores, monkeypatch, kind):
    store, versions = stores
    mem_id = store.add_memory('user', 'preference', 'original')
    versions.snapshot(store.get_memory(mem_id), 'edit')
    other = store.add_memory('other', 'preference', 'kept')
    versions.snapshot(store.get_memory(other), 'edit')
    generation_store.tombstone('user')
    with monkeypatch.context() as fault:
        if kind == 'vector':
            fault.setattr(store._collection, 'delete', lambda **kwargs: None)
            call = store.delete_user_memories
        else:
            fault.setattr(versions, '_delete_user', lambda _: 0)
            call = versions.delete_user
        with pytest.raises(RuntimeError, match='残留'):
            call('user')
    store.delete_user_memories('user')
    versions.delete_user('user')
    assert store.count_user_memories('user') == versions.count_user('user') == 0
    assert store.get_memory(other) and versions.count_user('other') == 1


def test_count_read_error_is_not_false_zero(stores, monkeypatch):
    store, _ = stores
    monkeypatch.setattr(store._collection, 'get', lambda **_: (_ for _ in ()).throw(OSError('unreadable')))
    with pytest.raises(OSError):
        store.count_user_memories('user')


def test_ordinary_clear_and_single_delete_keep_restore_for_live_account(stores):
    store, versions = stores
    mem_id = store.add_memory('user', 'preference', 'original')
    store.delete_memory(mem_id)
    saved = versions.get_version('user', mem_id)
    assert saved['action'] == 'delete' and store.get_memory(mem_id) is None
    store.restore_memory(mem_id, saved['content'], saved['metadata'])
    assert store.get_memory(mem_id)['content'] == 'original'
    store.delete_user_memories('user')
    assert not generation_store.snapshot('user').get('deleted')
    assert store.add_memory('user', 'preference', 'new')


def test_restore_snapshot_reads_latest_fields_after_provider_returns(stores, monkeypatch):
    store, versions = stores
    mem_id = store.add_memory('user', 'preference', 'original')
    before = store.get_memory(mem_id)
    entered, release = Event(), Event()

    def delayed(texts):
        entered.set()
        assert release.wait(5)
        return embeddings(texts)

    monkeypatch.setattr(module, 'embeddings', type('Embedding', (), {
        '__call__': lambda self, texts: delayed(texts), 'profile': lambda self: embeddings.profile()})())
    with ThreadPoolExecutor(max_workers=2) as pool:
        restoring = pool.submit(store.restore_memory, mem_id, 'restored', before, snapshot_current=True)
        try:
            assert entered.wait(5)
            store.update_memory_topic(mem_id, 'intervening change')
        finally:
            release.set()
        assert restoring.result(5)['content'] == 'restored'
    latest = versions.get_version('user', mem_id)
    assert latest['action'] == 'restore' and latest['metadata']['topic'] == 'intervening change'
