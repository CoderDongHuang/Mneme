from dataclasses import replace
from app.agents import trace_store
from app.core import privacy


def store(tmp_path, monkeypatch):
    monkeypatch.setattr(trace_store, "settings", replace(trace_store.settings, auxiliary_store_backend="sqlite"))
    monkeypatch.setattr(privacy, "settings", replace(privacy.settings, auxiliary_store_backend="sqlite"))
    policy = privacy.PrivacyStore(str(tmp_path / "privacy.db"))
    monkeypatch.setattr(trace_store, "privacy_store", policy)
    return trace_store.AgentTraceStore(str(tmp_path / "trace.db")), policy


def test_summary_is_user_scoped_retention_limited_and_contains_no_payloads(tmp_path, monkeypatch):
    traces, policy = store(tmp_path, monkeypatch)
    traces.record("alice", "s", "pre_llm.complete", "ok", {"confidence": 0.3, "message": "private"})
    traces.record("alice", "s", "knowledge_retrieval.result", "ok", {"chunk_count": 0})
    traces.record("bob", "s", "pre_llm.complete", "error", error="secret")
    policy.save("alice", True, 1)
    result = traces.quality_summary("alice", 90)
    assert result["window_days"] == 1
    assert result["low_intent_confidence"] == 1
    assert result["empty_retrievals"] == 1
    assert result["errors"] == 0
    assert "private" not in str(result)
    assert "secret" not in str(result)
    with traces._connect() as conn:
        conn.execute("UPDATE agent_trace SET created_at=datetime('now','-2 days') WHERE user_id='alice'")
    assert traces.quality_summary("alice")["status"] == "insufficient_data"


def test_invalid_confidence_not_reported_as_real_sample(tmp_path, monkeypatch):
    traces, _ = store(tmp_path, monkeypatch)
    traces.record("alice", "s", "pre_llm.complete", "ok", {"confidence": "NaN"})
    traces.record("alice", "s", "pre_llm.complete", "ok", {"confidence": -1})
    traces.record("alice", "s", "knowledge_retrieval.result", "ok", {"chunk_count": True})
    result = traces.quality_summary("alice")
    assert result["classified"] == 0
    assert result["invalid_payloads"] == 3
    assert result["retrievals"] == 0
