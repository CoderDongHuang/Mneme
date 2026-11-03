"""A storage outage is not an empty memory set or permission to replace it."""
import io
import logging
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.core.errors import MemoryReadUnavailable
from app.memory.long_term_memory import LongTermMemoryManager
from app.memory.memory_store import MemoryVectorStore
from app.memory.reflection_scheduler import reflection_scheduler
import app.memory.memory_store as storage_module
import app.api.memory as api_module
import app.memory.reflection_scheduler as scheduler_module
from main import app


@pytest.fixture
def resources(monkeypatch):
    store = object.__new__(MemoryVectorStore)
    collection = store._collection = Mock()
    collection.get.side_effect = OSError('PRIVATE_MEMORY_STORAGE_CANARY')
    manager = LongTermMemoryManager()
    manager._store = store
    monkeypatch.setattr(api_module, 'long_term_memory', manager)
    return store, collection, manager


@pytest.mark.parametrize('category', ['preference', 'weak_point', 'progress'])
def test_category_failure_does_not_poison_cache_and_retry_reads_real_data(resources, category):
    _, collection, manager = resources
    read = {'preference': manager.get_preferences, 'weak_point': manager.get_weak_points,
            'progress': manager.get_progress}[category]
    with pytest.raises(MemoryReadUnavailable):
        read('reader')
    assert manager._cache == {}
    collection.get.side_effect = None
    collection.get.return_value = {'ids': ['existing'], 'documents': ['kept content'],
                                   'metadatas': [{'category': category, 'importance': .6}]}
    recovered = read('reader')
    assert (recovered if category == 'progress' else recovered[0])['content'] == 'kept content'
    assert collection.get.call_count == 2
    read('reader')
    assert collection.get.call_count == 2  # Only a successful read may populate the cache.


@pytest.mark.parametrize('category', ['weak_point', 'progress'])
def test_missing_prerequisite_read_blocks_all_mutations_and_has_safe_503(resources, category):
    _, collection, _ = resources
    response = TestClient(app).post('/api/v1/memory/write', json={
        'user_id': 'reader', 'entry': {'category': category, 'content': 'new/section', 'topic': 'topic'},
    })
    assert response.status_code == 503
    assert response.json() == {'code': 'MEMORY_READ_UNAVAILABLE', 'detail': '长期记忆暂时无法读取，请稍后重试'}
    collection.add.assert_not_called()
    collection.delete.assert_not_called()
    collection.update.assert_not_called()
    collection.upsert.assert_not_called()


def test_http_read_failure_is_not_success_with_empty_preferences(resources):
    response = TestClient(app).post('/api/v1/memory/read', json={'user_id': 'reader', 'memory_types': ['preference']})
    assert response.status_code == 503
    assert 'preferences' not in response.json()


def test_empty_storage_remains_valid_empty_data(resources):
    store, collection, manager = resources
    collection.get.side_effect = None
    collection.get.return_value = {'ids': [], 'documents': [], 'metadatas': []}
    assert manager.get_all_memories('reader') == {'preferences': [], 'weak_points': [], 'progress': None}
    assert store.list_users() == []


def test_maintenance_enumeration_outage_is_not_reported_as_no_users(resources, monkeypatch):
    store, collection, _ = resources
    monkeypatch.setattr(scheduler_module, 'memory_store', store)
    decay = Mock()
    monkeypatch.setattr(scheduler_module.long_term_memory, 'decay_weak_points', decay)
    with pytest.raises(MemoryReadUnavailable):
        reflection_scheduler.run_memory_maintenance()
    decay.assert_not_called()
    collection.get.side_effect = None
    collection.get.return_value = {'metadatas': [{'user_id': 'reader'}, {'user_id': 'other'}]}
    assert set(store.list_users()) == {'reader', 'other'}


def test_storage_context_is_absent_from_diagnostic_logs_and_http(resources):
    store, _, _ = resources
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    storage_module.logger.addHandler(handler)
    try:
        for call in [lambda: store.get_by_category('reader', 'preference'), store.list_users]:
            with pytest.raises(MemoryReadUnavailable) as raised:
                call()
            assert 'PRIVATE_MEMORY_STORAGE_CANARY' not in str(raised.value)
        response = TestClient(app).post('/api/v1/memory/read', json={'user_id': 'reader'})
        assert response.status_code == 503
        assert 'PRIVATE_MEMORY_STORAGE_CANARY' not in response.text
    finally:
        storage_module.logger.removeHandler(handler)
    assert 'PRIVATE_MEMORY_STORAGE_CANARY' not in buffer.getvalue()
    assert 'read_category' in buffer.getvalue() and 'list_users' in buffer.getvalue()
