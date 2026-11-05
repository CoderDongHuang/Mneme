"""Final evidence reads raw stores, even after the account becomes invisible."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import account_cleanup as report, chat
from app.core.privacy import PrivacyStore
from app.knowledge.generations import generation_store, StaleGeneration
from app.memory.session_store import SessionStore
from app.memory.session_persistence import SessionPersistence
from app.memory import session_history
from app.memory.session_scope import account_session
from app.models.chat import Message
from app.tools.registry import ToolRegistry, ToolSpec


def test_tombstone_does_not_hide_raw_privacy_and_expired_session_residuals(tmp_path, monkeypatch):
    privacy = PrivacyStore(str(tmp_path / 'privacy.sqlite3'))
    sessions = SessionStore(str(tmp_path / 'sessions'))
    for user in ('target', 'other'):
        privacy.save(user, False, 1)
        sessions._save(user, {'11': {'last_updated': '2000-01-01T00:00:00'}})
        with account_session(user) as state:
            session_history.save(state, 'orphan', [Message(role='user', content='retained', timestamp='2000')])
            state['session_histories'][session_history.session_key('orphan')]['expires_at'] = 1
    monkeypatch.setattr(report, 'privacy_store', privacy)
    monkeypatch.setattr(report, 'session_store', sessions)
    generation_store.tombstone('target')
    counts = report.deletion_report('target')
    assert counts['account_fence'] == 0
    assert counts['privacy_rows'] == counts['session_manifest'] == 1
    assert counts['sql_session_histories'] == 1  # Raw expiry/tombstone must not conceal an orphan.
    privacy.delete('target')
    sessions.delete_user('target')
    counts = report.deletion_report('target')
    assert counts['privacy_rows'] == counts['session_manifest'] == 0
    assert privacy.count_user('other') == len(sessions.cleanup_session_ids('other')) == 1


@pytest.mark.parametrize('bad', [False, '0', 0.0, -2, None])
def test_untrusted_count_types_remain_unknown(monkeypatch, bad):
    monkeypatch.setattr(report.tool_registry, 'count_user_governance', lambda _: bad)
    assert report.deletion_report('target')['tool_governance'] == -1


def test_each_failure_is_unknown_without_hiding_other_store_counts(monkeypatch):
    monkeypatch.setattr(report.privacy_store, 'count_user', Mock(side_effect=OSError('secret payload')))
    monkeypatch.setattr(report.tool_registry, 'count_user_governance', lambda _: 2)
    counts = report.deletion_report('target')
    assert counts['privacy_rows'] == -1
    assert counts['tool_governance'] == 2
    assert counts['account_fence'] == 1
    assert 'secret payload' not in str(counts)


def test_endpoint_requires_internal_service_auth(monkeypatch):
    import main
    app = FastAPI()
    app.include_router(chat.router)
    app.add_middleware(main.InternalServiceAuthMiddleware)
    monkeypatch.setattr(main, 'settings', replace(main.settings, skip_internal_auth=False))
    monkeypatch.setattr(main.internal_tokens, 'accepts', lambda token: token == 'qa-service-token')
    monkeypatch.setattr(report, 'deletion_report', lambda user: {'account_fence': 0})
    with TestClient(app) as client:
        assert client.get('/api/v1/admin/user/1/deletion-report').status_code == 401
        response = client.get('/api/v1/admin/user/1/deletion-report', headers={'X-Internal-Service-Token': 'qa-service-token'})
        assert response.status_code == 200
        assert response.json() == {'account_fence': 0}


def test_governance_cannot_reappear_from_late_quota_or_approval_write():
    registry = ToolRegistry()
    registry.register(ToolSpec('qa', 'qa', {}, 'qa'), lambda: None)
    registry.approve('qa', 'target', 'admin')
    registry._consume_quota('qa', 'target', 1)
    registry._consume_quota('qa', 'other', 1)
    assert registry.count_user_governance('target') == 2
    generation_store.tombstone('target')
    registry.delete_user_governance('target')
    for write in (lambda: registry.approve('qa', 'target', 'admin'), lambda: registry._consume_quota('qa', 'target', 1)):
        with pytest.raises(StaleGeneration):
            write()
    assert registry.count_user_governance('target') == 0
    assert registry.count_user_governance('other') == 1


def test_inflight_quota_finishes_before_delete_fence_and_cannot_replay():
    registry = ToolRegistry()
    entered, release, deleting = Event(), Event(), Event()
    original = registry._consume_active_quota

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        original(*args)

    registry._consume_active_quota = delayed

    def cleanup():
        deleting.set()
        generation_store.tombstone('target')
        registry.delete_user_governance('target')

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(registry._consume_quota, 'qa', 'target', 1)
        try:
            assert entered.wait(5)
            deletion = pool.submit(cleanup)
            assert deleting.wait(5)
            assert not deletion.done()
        finally:
            release.set()
        writing.result(5)
        deletion.result(5)
    assert registry.count_user_governance('target') == 0


def test_scoped_redis_count_is_unavailable_on_disconnect_and_escapes_user_globs():
    persistence = object.__new__(SessionPersistence)
    persistence._ensure_connection = lambda: False
    with pytest.raises(RuntimeError):
        persistence.count_user_sessions('old*?[user]')
    persistence._ensure_connection = lambda: True
    persistence._redis = Mock()
    persistence._redis.scan_iter.return_value = iter(['key1', 'key2'])
    assert persistence.count_user_sessions('old*?[user]') == 2
    pattern = persistence._redis.scan_iter.call_args.kwargs['match']
    assert '*' not in pattern[:-1] and '?' not in pattern and '[' not in pattern
