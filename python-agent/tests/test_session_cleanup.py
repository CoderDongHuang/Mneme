"""Deletion must enumerate raw metadata and verify Redis/file postconditions."""
import json
import time
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat
from app.memory.session_persistence import SessionPersistence
from app.memory.session_store import SessionStore
from app.memory.short_term_memory import ShortTermMemoryManager
from app.memory.working_memory import WorkingMemoryManager


@pytest.fixture
def resources(tmp_path, monkeypatch):
    store = SessionStore(str(tmp_path))
    persistence = object.__new__(SessionPersistence)
    persistence._available = True
    persistence._last_attempt = time.monotonic()
    persistence._redis = Mock()
    keys = {'mneme:session:11', 'mneme:session:12', 'mneme:session:22'}
    persistence._redis.delete.side_effect = lambda key: keys.discard(key)
    persistence._redis.exists.side_effect = lambda *requested: sum(key in keys for key in requested)
    short = ShortTermMemoryManager()
    working = WorkingMemoryManager()
    monkeypatch.setattr('app.memory.short_term_memory.session_persistence', persistence)
    monkeypatch.setattr(chat, 'session_persistence', persistence)
    monkeypatch.setattr(chat, 'short_term_memory', short)
    monkeypatch.setattr(chat, 'working_memory', working)
    monkeypatch.setattr(chat, 'session_store', store)
    traces = Mock(return_value=1)
    monkeypatch.setattr(chat.agent_trace_store, 'delete_user', traces)
    monkeypatch.setattr(chat.privacy_store, 'delete', Mock())
    app = FastAPI()
    app.include_router(chat.router)
    return store, persistence, keys, traces, TestClient(app, raise_server_exceptions=False)


def test_cleanup_reads_expired_manifest_without_calling_ttl_ui_list(resources, monkeypatch):
    store, _, keys, _, http = resources
    store._save('alice', {'11': {'last_updated': '2000-01-01T00:00:00'}, '12': {}})
    store._save('bob', {'22': {}})
    monkeypatch.setattr(store, 'get_sessions', Mock(side_effect=AssertionError('must not prune')))
    assert http.delete('/api/v1/admin/user/alice').status_code == 200
    assert not store.cleanup_session_ids('alice')
    assert keys == {'mneme:session:22'}
    assert store.cleanup_session_ids('bob') == ['22']


def test_canonical_batch_cleans_keys_missing_from_optional_metadata(resources):
    _, _, keys, _, http = resources
    response = http.post('/api/v1/admin/user/alice/session-cache', json={'session_ids': ['11', '12']})
    assert response.json() == {'status': 'verified', 'checked_sessions': 2, 'redis_sessions': 0}
    assert keys == {'mneme:session:22'}
    assert http.post('/api/v1/admin/user/alice/session-cache', json={'session_ids': ['11', '12']}).status_code == 200


@pytest.mark.parametrize('failure', ['noop_delete', 'read_error', 'noop_clear'])
def test_redis_failure_retains_manifest_and_retry_rechecks_all_keys(resources, monkeypatch, failure):
    store, persistence, keys, traces, http = resources
    store._save('alice', {'11': {}, '12': {}})
    with monkeypatch.context() as fault:
        if failure == 'noop_delete':
            fault.setattr(persistence._redis, 'delete', lambda _: 0)
        elif failure == 'read_error':
            fault.setattr(persistence._redis, 'exists', Mock(side_effect=OSError('offline')))
        else:
            fault.setattr(chat.short_term_memory, 'clear', lambda _: None)
        assert http.delete('/api/v1/admin/user/alice').status_code == 500
        assert store.cleanup_session_ids('alice') == ['11', '12']
        assert 'mneme:session:22' in keys
    persistence._available = True
    assert http.delete('/api/v1/admin/user/alice').status_code == 200
    assert keys == {'mneme:session:22'}
    assert not store.cleanup_session_ids('alice')
    assert traces.call_count >= 1


@pytest.mark.parametrize('content', ['{broken', '[]', '{"11": null}'])
def test_corrupt_manifest_is_not_an_empty_success(resources, content):
    store, _, keys, traces, http = resources
    path = store._get_file_path('alice')
    with open(path, 'w', encoding='utf8') as handle:
        handle.write(content)
    assert http.delete('/api/v1/admin/user/alice').status_code == 500
    traces.assert_not_called()
    assert len(keys) == 3


def test_later_stage_failure_keeps_raw_cleanup_scope_for_retry(resources, monkeypatch):
    store, _, _, traces, http = resources
    store._save('alice', {'11': {}, '12': {}})
    traces.side_effect = OSError('disk')
    assert http.delete('/api/v1/admin/user/alice').status_code == 500
    assert store.cleanup_session_ids('alice') == ['11', '12']
    traces.side_effect = None
    assert http.delete('/api/v1/admin/user/alice').status_code == 200


def test_silent_file_unlink_failure_is_detected(resources, monkeypatch):
    store, _, _, _, http = resources
    store._save('alice', {'11': {}})
    with monkeypatch.context() as fault:
        fault.setattr('app.memory.session_store.os.unlink', lambda _: None)
        assert http.delete('/api/v1/admin/user/alice').status_code == 500
        assert store.cleanup_session_ids('alice') == ['11']
    assert http.delete('/api/v1/admin/user/alice').status_code == 200


@pytest.mark.parametrize('ids', [[], ['11', 'not-an-id'], ['11'] * 1001, ['١١']])
def test_bad_batch_is_rejected_before_any_key_is_deleted(resources, ids):
    _, _, keys, _, http = resources
    assert http.post('/api/v1/admin/user/alice/session-cache', json={'session_ids': ids}).status_code == 422
    assert len(keys) == 3


def test_strict_manifest_read_does_not_swallow_permission_error(resources, monkeypatch):
    store, _, _, _, _ = resources
    with monkeypatch.context() as fault:
        fault.setattr('builtins.open', Mock(side_effect=PermissionError('denied')))
        with pytest.raises(PermissionError):
            store.cleanup_session_ids('alice')
    # Empty is a valid manifest, as distinct from an unreadable one.
    store._save('alice', json.loads('{}'))
    assert store.cleanup_session_ids('alice') == []
