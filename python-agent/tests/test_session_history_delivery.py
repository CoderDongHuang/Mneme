"""Actual SQL transactions: duplicate delivery, lost ACK and cache outage."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.time import utc_now
from app.knowledge.generations import generation_store, StaleGeneration
from app.memory import session_history
from app.memory.session_persistence import session_persistence
from app.memory.session_scope import account_session, tombstone_session
from app.memory.short_term_memory import ShortTermMemoryManager
from app.models.chat import Message


@pytest.fixture(autouse=True)
def redis_offline(monkeypatch):
    monkeypatch.setattr(session_persistence, "_ensure_connection", lambda: False)


def message(content="private content", role="user"):
    return Message(role=role, content=content, timestamp=utc_now().isoformat(), token_count=500)


def test_concurrent_workers_and_cold_instance_append_once_per_role():
    managers = [ShortTermMemoryManager(), ShortTermMemoryManager()]
    def append(i):
        managers[i % 2].add_message("s", message(role="user" if i % 3 else "assistant"),
                                  user_id="alice", delivery_id="turn")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(48)))
    cold = ShortTermMemoryManager()
    history = cold.get_history("s", user_id="alice")
    assert sorted(item.role for item in history) == ["assistant", "user"]
    state = generation_store.snapshot("alice")
    value = state["session_histories"][session_history.session_key("s")]
    assert len(value["deliveries"]) == 2 and "turn" not in str(value["deliveries"])
    for role in ("assistant", "user"):
        cold.add_message("s", message(role=role), user_id="alice", delivery_id="turn")
    assert generation_store.snapshot("alice") == state  # No expiry/revision refresh.
    assert cold.get_history("s", user_id="alice") == history


@pytest.mark.parametrize("stage", ["rollback", "lost_ack"])
def test_failed_commit_or_lost_ack_cannot_publish_phantom_or_duplicate(monkeypatch, stage):
    manager = ShortTermMemoryManager()
    original = generation_store.locked
    @contextmanager
    def fail(user):
        with original(user) as state:
            yield state
            if stage == "rollback":
                raise OSError("commit unavailable")
        raise OSError("ack lost")
    with monkeypatch.context() as fault:
        fault.setattr(generation_store, "locked", fail)
        with pytest.raises(OSError):
            manager.add_message("s", message(), user_id="alice", delivery_id="turn")
    assert len(manager.get_history("s", user_id="alice")) == (0 if stage == "rollback" else 1)
    manager.add_message("s", message(), user_id="alice", delivery_id="turn")
    assert len(ShortTermMemoryManager().get_history("s", user_id="alice")) == 1


def test_conflicting_payload_rejected_and_unscoped_identical_messages_retained():
    manager = ShortTermMemoryManager()
    manager.add_message("s", message("first"), user_id="alice", delivery_id="turn")
    before = generation_store.snapshot("alice")
    with pytest.raises(ValueError, match="内容发生变化"):
        manager.add_message("s", message("different"), user_id="alice", delivery_id="turn")
    assert generation_store.snapshot("alice") == before
    manager.add_message("s", message("first"), user_id="alice")
    manager.add_message("s", message("first"), user_id="alice")
    assert len(manager.get_history("s", user_id="alice")) == 3
    manager.add_message("s", message(), user_id="bob", delivery_id="turn")
    manager.add_message("other", message(), user_id="alice", delivery_id="turn")


def test_summary_keeps_delivery_receipts_and_replay_does_not_restore_old_message(monkeypatch):
    manager = ShortTermMemoryManager()
    for i in range(20):
        manager.add_message("s", message(str(i)), user_id="alice", delivery_id=str(i))
    monkeypatch.setattr("app.memory.short_term_memory.llm", SimpleNamespace(invoke=lambda _: SimpleNamespace(content="summary")))
    manager.summarize("s", user_id="alice")
    before = manager.get_history("s", user_id="alice")
    assert before[0].role == "system" and len(before) < 20
    ShortTermMemoryManager().add_message("s", message("0"), user_id="alice", delivery_id="0")
    assert manager.get_history("s", user_id="alice") == before


def test_expiry_removes_body_and_receipts_even_with_hot_local_cache(monkeypatch):
    manager = ShortTermMemoryManager()
    manager.add_message("s", message(), user_id="alice", delivery_id="turn")
    later = utc_now() + timedelta(days=3)
    monkeypatch.setattr(session_history, "utc_now", lambda: later)
    assert manager.get_history("s", user_id="alice") == []
    assert generation_store.snapshot("alice")["session_histories"] == {session_history.session_key("s"): {"expired": True}}
    # Expired history cannot reappear from an old mirror; a new active period
    # intentionally starts a new retention/deduplication window.
    manager.add_message("s", message("new period"), user_id="alice", delivery_id="turn")
    assert [m.content for m in manager.get_history("s", user_id="alice")] == ["new period"]


def test_raw_cleanup_counts_orphans_and_tombstone_wins_over_receipt(monkeypatch):
    manager = ShortTermMemoryManager()
    for user in ("alice", "bob"):
        manager.add_message("orphan", message(), user_id=user, delivery_id="turn")
    generation_store.tombstone("alice")
    assert session_history.count_user("alice") == 1
    with pytest.raises(StaleGeneration):
        manager.add_message("orphan", message(), user_id="alice", delivery_id="turn")
    backend = SimpleNamespace(scan_iter=lambda **_: iter([]))
    monkeypatch.setattr(session_persistence, "_ensure_connection", lambda: True)
    monkeypatch.setattr(session_persistence, "_redis", backend)
    session_persistence.delete_user_sessions("alice")
    assert session_history.count_user("alice") == 0
    assert session_history.count_user("bob") == 1
    tombstone_session("bob", "orphan")
    backend.delete = lambda _: None
    backend.exists = lambda *_: 0
    manager.clear("orphan", user_id="bob")
    assert session_history.count_user("bob") == 0


@pytest.mark.parametrize("bad", [[], {"messages": "PRIVATE_CANARY"}, {"expired": 1}])
def test_corrupt_history_fails_closed_without_exposing_body(bad):
    with account_session("alice") as state:
        state["session_histories"] = {session_history.session_key("s"): bad}
    with pytest.raises(ValueError, match="会话持久历史损坏") as caught:
        ShortTermMemoryManager().get_history("s", user_id="alice")
    assert caught.value.__suppress_context__
    assert "PRIVATE_CANARY" not in str(caught.value)


def test_unmigrated_legacy_history_is_not_overwritten_during_redis_outage():
    from app.memory.session_scope import advance_revision
    with account_session("alice") as state:
        advance_revision(state, "s")
    with pytest.raises(RuntimeError, match="旧会话历史暂不可用"):
        ShortTermMemoryManager().add_message("s", message(), user_id="alice", delivery_id="turn")
    assert session_history.count_user("alice") == 0


def test_pre_revision_legacy_history_is_not_overwritten_during_redis_outage():
    from app.memory.session_store import session_store
    session_store.register_session("alice", "legacy")
    with pytest.raises(RuntimeError, match="旧会话历史暂不可用"):
        ShortTermMemoryManager().add_message("legacy", message(), user_id="alice", delivery_id="turn")
    assert session_history.count_user("alice") == 0


@pytest.mark.parametrize("bad", [[], "private", {"messages": [], "deliveries": {}, "expires_at": float("inf")},
    {"messages": [{**message().model_dump(), "private": "PRIVATE_CANARY"}], "deliveries": {}, "expires_at": 9999999999}])
def test_corrupt_top_level_or_message_schema_rejects_append(bad):
    with account_session("alice") as state:
        state["session_histories"] = bad if not isinstance(bad, dict) else {session_history.session_key("s"): bad}
    with pytest.raises(ValueError, match="会话持久历史损坏") as caught:
        ShortTermMemoryManager().add_message("s", message(), user_id="alice", delivery_id="turn")
    assert caught.value.__suppress_context__
    assert "PRIVATE_CANARY" not in str(caught.value)
