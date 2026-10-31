from datetime import datetime, timedelta, timezone

import pytest

from app.core.time import parse_utc, utc_now
from app.knowledge import task_tracker
from app.memory import session_store


@pytest.mark.parametrize('value', [
    '2026-10-30T23:30:00', '2026-10-30 23:30:00',
    '2026-10-30T23:30:00Z', '2026-10-31T07:30:00+08:00',
])
def test_legacy_utc_and_explicit_offsets_are_the_same_instant(value):
    assert parse_utc(value) == datetime(2026, 10, 30, 23, 30, tzinfo=timezone.utc)
    assert utc_now().utcoffset() == timedelta(0)


def test_session_expiry_and_order_accept_mixed_legacy_and_aware_times(tmp_path, monkeypatch):
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(session_store, 'utc_now', lambda: now)
    store = session_store.SessionStore(str(tmp_path))
    store._save('utc-qa', {
        'older': {'last_updated': '2026-10-30T23:00:00+08:00'},
        'newer': {'last_updated': '2026-10-30T22:00:00'},
        'expired': {'last_updated': '2026-09-01T00:00:00'},
        'expired-aware': {'last_updated': '2026-09-01T00:00:00+08:00'},
    })
    assert [row['id'] for row in store.get_sessions('utc-qa')] == ['newer', 'older']
    store.update_title('utc-qa', 'newer', 'Updated')
    assert store._load('utc-qa')['newer']['last_updated'] == now.isoformat()


def test_task_expiry_handles_old_utc_and_new_aware_timestamps(monkeypatch):
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    monkeypatch.setattr(task_tracker, 'utc_now', lambda: now)
    monkeypatch.setattr(task_tracker, '_task_store', {
        'expired': {'created_at': '2026-10-30T22:59:59'},
        'active': {'created_at': '2026-10-31T07:30:00+08:00'},
    })
    assert task_tracker.get_task('active') is not None
    assert task_tracker.get_task('expired') is None
    created = task_tracker.create_task()
    assert task_tracker.get_task(created)['created_at'] == now.isoformat()


@pytest.mark.parametrize('timestamp', ['2026-10-30T23:40:00', '2026-10-31T07:40:00+08:00'])
def test_distillation_idle_window_uses_utc_for_legacy_and_aware_history(monkeypatch, timestamp):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.agents import nodes
    from app.models.chat import Message

    monkeypatch.setattr(nodes, 'utc_now', lambda: datetime(2026, 10, 31, tzinfo=timezone.utc))
    monkeypatch.setattr(nodes, 'settings', SimpleNamespace(distillation_idle_minutes=15))
    monkeypatch.setattr(nodes.short_term_memory, 'get_history', lambda _: [
        Message(role='assistant', content='Earlier', timestamp=timestamp),
        Message(role='user', content='Now', timestamp='2026-10-31T00:00:00Z'),
    ])
    distill = Mock(return_value=[])
    monkeypatch.setattr(nodes, 'distill_conversation', distill)
    monkeypatch.setattr(nodes, 'apply_distilled_entries', lambda *_: [])
    nodes.memory_write_node({'user_id': 'utc-qa', 'session_id': 'utc-session'})
    distill.assert_called_once()
