import pytest
from dataclasses import replace
from unittest.mock import Mock
from app.core import privacy
from app.agents import trace_store
from app.knowledge.ingestion import ingest_document
from app.knowledge.retriever import retrieve
from app.memory.distillation import distill_conversation


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "settings", replace(privacy.settings, auxiliary_store_backend="sqlite"))
    store = privacy.PrivacyStore(str(tmp_path / "privacy.db"))
    monkeypatch.setattr(privacy, "privacy_store", store)
    monkeypatch.setattr(trace_store, "privacy_store", store)
    return store


def test_revocation_scoped_and_persistent(policy):
    policy.save("alice", False, 1)
    assert not policy.get("alice")["cloud_allowed"]
    privacy.require_cloud_processing("bob")
    with pytest.raises(PermissionError):
        privacy.require_cloud_processing("alice")
    policy.save("alice", True, 2)
    privacy.require_cloud_processing("alice")


def test_denied_workflows_do_not_access_cloud(policy):
    policy.save("alice", False, 1)
    for call in (lambda: ingest_document("alice", "kb", "nonexistent"),
                 lambda: retrieve("alice", "kb", "query"),
                 lambda: distill_conversation("alice", "session", [])):
        with pytest.raises(PermissionError):
            call()


def test_retention_and_delete_are_user_scoped(policy, tmp_path):
    store = trace_store.AgentTraceStore(str(tmp_path / "trace.db"))
    for user in ("alice", "bob"):
        store.record(user, "s", "node", "ok")
    with store._connect() as conn:
        conn.execute("UPDATE agent_trace SET created_at=datetime('now','-3 days')")
    policy.save("alice", False, 1)
    assert store.prune_policies() == 1
    assert store.list_session("alice", "s") == []
    assert len(store.list_session("bob", "s")) == 1
    assert store.delete_user("alice") == 0


def test_privacy_failure_is_closed(monkeypatch):
    monkeypatch.setattr(privacy, "privacy_store", Mock(get=Mock(side_effect=RuntimeError("offline"))))
    with pytest.raises(RuntimeError):
        privacy.require_cloud_processing("alice")
