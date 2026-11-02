"""Deletion and shared invalidation must reject late cache publication."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from app.knowledge.generations import generation_store, StaleGeneration
from app.memory.cache_revision import MemoryCacheRevision
from app.memory.long_term_memory import LongTermMemoryManager
import app.memory.long_term_memory as module


@pytest.fixture
def resources(monkeypatch):
    revision = MemoryCacheRevision()
    keys = {revision._key('alice'): '99', revision._key('bob'): '40'}
    revision._redis = Mock()
    revision._redis.delete.side_effect = lambda key: keys.pop(key, None)
    revision._redis.exists.side_effect = lambda key: int(key in keys)
    monkeypatch.setattr(module, 'memory_cache_revision', revision)
    manager = LongTermMemoryManager()
    manager._store = Mock()
    manager._store.get_by_category.return_value = [{'content': 'private', 'nested': {'value': 1}}]
    return manager, revision, keys


@pytest.mark.parametrize('read', ['get_preferences', 'get_weak_points', 'get_progress'])
def test_deleted_account_cannot_read_a_hot_cache(resources, read):
    manager, revision, keys = resources
    other = LongTermMemoryManager()
    other._store = manager._store
    getattr(manager, read)('alice')
    getattr(other, read)('bob')
    generation_store.tombstone('alice')
    manager._invalidate_cache('alice')
    with pytest.raises(StaleGeneration):
        getattr(manager, read)('alice')
    assert 'alice' not in manager._cache
    assert revision._key('alice') not in keys
    assert getattr(other, read)('bob')
    assert revision._key('bob') in keys


def test_provider_read_wait_does_not_block_deletion_or_publish_late_result(resources):
    manager, _, _ = resources
    entered, release = Event(), Event()

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return [{'content': 'late private result'}]

    manager._store.get_by_category.side_effect = paused
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(manager.get_preferences, 'alice')
        try:
            assert entered.wait(5)
            pool.submit(generation_store.tombstone, 'alice').result(3)
            manager._invalidate_cache('alice')
        finally:
            release.set()
        with pytest.raises(StaleGeneration):
            reading.result(5)
    assert 'alice' not in manager._cache


def test_completed_invalidation_cannot_label_old_query_result_as_current(resources):
    manager, revision, _ = resources

    def reading(*args, **kwargs):
        if manager._store.get_by_category.call_count == 1:
            revision.bump('alice')
            return [{'content': 'old'}]
        return [{'content': 'new'}]

    manager._store.get_by_category.side_effect = reading
    assert manager.get_preferences('alice') == [{'content': 'new'}]
    assert manager._store.get_by_category.call_count == 2
    assert manager.get_preferences('alice') == [{'content': 'new'}]


def test_continuous_changes_fail_instead_of_returning_stale_or_looping(resources):
    manager, revision, _ = resources

    def changing(*args, **kwargs):
        revision.bump('alice')
        return [{'content': 'outdated'}]

    manager._store.get_by_category.side_effect = changing
    with pytest.raises(RuntimeError, match='正在更新'):
        manager.get_preferences('alice')
    assert manager._store.get_by_category.call_count == 3
    assert not manager._cache


def test_returned_values_cannot_mutate_cached_payload(resources):
    manager, _, _ = resources
    first = manager.get_preferences('alice')
    first[0]['nested']['value'] = 50
    second = manager.get_preferences('alice')
    assert second[0]['nested']['value'] == 1
    second.clear()
    assert len(manager.get_preferences('alice')) == 1


@pytest.mark.parametrize('failure', ['noop', 'read_error', 'offline'])
def test_legacy_revision_cleanup_failure_is_not_success_and_retry_works(resources, failure):
    manager, revision, keys = resources
    manager.get_preferences('alice')
    generation_store.tombstone('alice')
    redis_client = revision._redis
    if failure == 'noop':
        redis_client.delete.side_effect = lambda _: None
    elif failure == 'read_error':
        redis_client.exists.side_effect = OSError('private backend context')
    else:
        redis_client.delete.side_effect = OSError('private backend context')
    with pytest.raises(RuntimeError, match='无法确认') as raised:
        manager._invalidate_cache('alice')
    assert 'private backend context' not in str(raised.value)
    assert 'alice' not in manager._cache
    assert generation_store.snapshot('alice').get('deleted')
    redis_client.delete.side_effect = lambda key: keys.pop(key, None)
    redis_client.exists.side_effect = lambda key: int(key in keys)
    manager._invalidate_cache('alice')
    assert revision._key('alice') not in keys
    assert revision.bump('alice') == 0
    assert generation_store.snapshot('alice').get('deleted')


def test_two_revision_instances_share_durable_versions_without_redis(resources):
    _, first, _ = resources
    second = MemoryCacheRevision()
    assert first.bump('alice') == 1
    assert second.current('alice') == 1
    assert second.bump('alice') == 2
    assert first.current('alice') == 2
    first._redis.incr.assert_not_called()


def test_upgrade_cleanup_removes_only_durably_deleted_legacy_keys(resources):
    _, revision, keys = resources
    generation_store.tombstone('alice')
    revision._redis.scan_iter.side_effect = lambda **_: iter(list(keys))
    assert revision.cleanup_deleted_revisions() == 1
    assert keys == {revision._key('bob'): '40'}
    assert revision.cleanup_deleted_revisions() == 0


def test_upgrade_cleanup_never_guesses_deleted_on_durable_read_failure(resources, monkeypatch):
    _, revision, keys = resources
    revision._redis.scan_iter.side_effect = lambda **_: iter(list(keys))
    monkeypatch.setattr(generation_store, 'snapshot', Mock(side_effect=OSError('read failed')))
    with pytest.raises(OSError):
        revision.cleanup_deleted_revisions()
    revision._redis.delete.assert_not_called()
    assert len(keys) == 2


def test_upgrade_cleanup_rejects_silent_residue(resources):
    _, revision, _ = resources
    generation_store.tombstone('alice')
    revision._redis.scan_iter.side_effect = lambda **_: iter([revision._key('alice')])
    revision._redis.delete.side_effect = lambda _: None
    with pytest.raises(RuntimeError, match='无法确认'):
        revision.cleanup_deleted_revisions()


def test_durable_read_failure_never_serves_hot_payload(resources, monkeypatch):
    manager, _, _ = resources
    manager.get_preferences('alice')
    monkeypatch.setattr(generation_store, 'locked', Mock(side_effect=OSError('DB read failed')))
    with pytest.raises(OSError):
        manager.get_preferences('alice')


@pytest.mark.parametrize('value', [-1, '3', True, None])
def test_corrupt_shared_revision_is_not_a_cache_miss(resources, value):
    manager, _, _ = resources
    with generation_store.locked('alice') as state:
        state['memory_cache_revision'] = value
    with pytest.raises(ValueError, match='版本损坏'):
        manager.get_preferences('alice')
    manager._store.get_by_category.assert_not_called()
