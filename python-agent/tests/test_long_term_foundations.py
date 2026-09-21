import asyncio
from datetime import datetime, timezone
from contextvars import ContextVar
import sys

import pytest

import app.api.chat as chat_api
import app.api.memory as memory_api
from app.agents.trace_store import AgentTraceStore
from app.api.chat import _visual_region
from app.api.chat_stream import _source_payload
from app.api.knowledge import document_report
from app.memory.version_store import MemoryVersionStore
from app.memory.session_persistence import SessionPersistence
from app.memory.session_store import SessionStore
from app.tools.registry import SubprocessTool, ToolRegistry, ToolSpec, tool_registry
from app.core.internal_tokens import InternalTokenState
from app.core.config import settings
from app.memory.distillation import apply_distilled_entries
from unittest.mock import patch


def test_memory_version_store_snapshots_and_reads_latest(tmp_path):
    store = MemoryVersionStore(str(tmp_path / "versions.sqlite3"))
    memory = {
        "id": "mem_u1_test",
        "user_id": "u1",
        "category": "preference",
        "content": "喜欢图表讲解",
        "topic": "图表",
        "importance": 0.8,
    }

    assert store.snapshot(memory, "update") == 1
    assert store.snapshot({**memory, "content": "喜欢例题"}, "delete") == 2

    versions = store.list_versions("u1", "mem_u1_test")
    assert [item["version"] for item in versions] == [2, 1]
    latest = store.get_version("u1", "mem_u1_test")
    assert latest["content"] == "喜欢例题"
    assert latest["metadata"]["category"] == "preference"


def test_agent_trace_store_records_auditable_events(tmp_path):
    store = AgentTraceStore(str(tmp_path / "traces.sqlite3"))
    with store.span("u1", "s1", "intent_classification", {"has_kb": True}):
        pass
    store.record("u1", "s1", "pre_llm.complete", "ok", {"intent": "qa"})

    traces = store.list_session("u1", "s1")
    assert [trace["node"] for trace in traces] == [
        "pre_llm.complete",
        "intent_classification",
    ]
    assert traces[0]["payload"]["intent"] == "qa"


def test_trace_store_prunes_old_events(tmp_path):
    store = AgentTraceStore(str(tmp_path / "traces.sqlite3"))
    store.record("u1", "s1", "node", "ok")
    with store._connect() as connection:
        connection.execute(
            "UPDATE agent_trace SET created_at=datetime('now', '-40 days')"
        )

    assert store.prune(30) == 1
    assert store.list_session("u1", "s1") == []


def test_tool_registry_lists_audited_tool_contracts():
    tools = {tool["name"]: tool for tool in tool_registry.list_specs()}

    assert {"knowledge.retrieve", "memory.read", "memory.write"} <= set(tools)
    assert tools["knowledge.retrieve"]["audited"] is True
    assert "user_id" in tools["memory.write"]["input_schema"]


def test_source_payload_includes_visual_evidence_metadata():
    chunks = [
        {
            "content": "图表显示复习间隔提升。",
            "score": 0.91,
            "metadata": {
                "document_id": "doc1",
                "source": "report.pdf",
                "page": 3,
                "chunk_type": "table",
                "evidence_type": "visual",
                "visual_region": "0.1,0.2,0.7,0.8",
                "ocr_confidence": 0.88,
            },
        }
    ]

    source = _source_payload(chunks)[0]
    assert source["evidence_type"] == "visual"
    assert source["visual_page"] == 3
    assert source["ocr_confidence"] == 0.88
    assert _visual_region(chunks[0]["metadata"]) == [0.1, 0.2, 0.7, 0.8]


def test_memory_version_store_prunes_old_versions(tmp_path):
    store = MemoryVersionStore(str(tmp_path / "versions.sqlite3"))
    store.snapshot({"id": "mem_1", "user_id": "u1", "content": "old"}, "update")
    with store._connect() as connection:
        connection.execute(
            "UPDATE memory_version SET created_at=datetime('now', '-200 days')"
        )

    assert store.prune(180) == 1
    assert store.list_versions("u1", "mem_1") == []


def test_memory_version_store_deletes_only_requested_user(tmp_path):
    store = MemoryVersionStore(str(tmp_path / "versions.sqlite3"))
    store.snapshot({"id": "mem_1", "user_id": "u1", "content": "private"}, "update")
    store.snapshot({"id": "mem_2", "user_id": "u2", "content": "keep"}, "update")

    assert store.delete_user("u1") == 1
    assert store.list_versions("u1", "mem_1") == []
    assert len(store.list_versions("u2", "mem_2")) == 1


def test_agent_trace_store_deletes_only_requested_user(tmp_path):
    store = AgentTraceStore(str(tmp_path / "traces.sqlite3"))
    store.record("u1", "s1", "node", "ok")
    store.record("u2", "s2", "node", "ok")

    assert store.delete_user("u1") == 1
    assert store.list_session("u1", "s1") == []
    assert len(store.list_session("u2", "s2")) == 1


def test_account_cleanup_endpoints_remove_versions_and_traces(monkeypatch):
    memory_calls = []
    trace_calls = []
    monkeypatch.setattr(memory_api.memory_store, "delete_user_memories", lambda user_id: None)
    monkeypatch.setattr(memory_api.memory_version_store, "delete_user", lambda user_id: memory_calls.append(user_id) or 2)
    monkeypatch.setattr(chat_api.session_store, "get_sessions", lambda user_id: [])
    monkeypatch.setattr(chat_api.session_store, "delete_user", lambda user_id: None)
    monkeypatch.setattr(chat_api.agent_trace_store, "delete_user", lambda user_id: trace_calls.append(user_id) or 3)

    memory_result = asyncio.run(memory_api.delete_user_memories("u1"))
    session_result = asyncio.run(chat_api.delete_user_sessions("u1"))

    assert memory_calls == ["u1"]
    assert trace_calls == ["u1"]
    assert memory_result["versions"] == 2
    assert session_result["traces"] == 3


def test_session_file_delete_failure_is_not_silenced(tmp_path, monkeypatch):
    store = SessionStore(str(tmp_path))
    session_file = tmp_path / "u1.json"
    session_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("app.memory.session_store.os.unlink", lambda _path: (_ for _ in ()).throw(PermissionError("locked")))

    with pytest.raises(PermissionError, match="locked"):
        store.delete_user("u1")


def test_redis_delete_requires_available_backend(monkeypatch):
    persistence = object.__new__(SessionPersistence)
    monkeypatch.setattr(persistence, "_ensure_connection", lambda: False)

    with pytest.raises(RuntimeError, match="Redis 不可用"):
        persistence.delete_session("s1")


def test_document_report_aggregates_visual_and_ocr_metadata(monkeypatch):
    monkeypatch.setattr(
        "app.api.knowledge.vector_store.get_document_chunks",
        lambda user_id, kb_id, document_id: [
            {
                "id": "c1",
                "content": "text",
                "metadata": {
                    "page": 1,
                    "chunk_type": "text",
                    "ocr_confidence": 0.9,
                },
            },
            {
                "id": "c2",
                "content": "table",
                "metadata": {
                    "page": 1,
                    "chunk_type": "table",
                    "evidence_type": "visual",
                    "ocr_confidence": 0.7,
                },
            },
        ],
    )

    import asyncio

    report = asyncio.run(document_report("doc_1", "u1", "kb1"))
    assert report["chunk_count"] == 2
    assert report["chunk_types"] == {"text": 1, "table": 1}
    assert report["pages"][0]["visual_evidence_count"] == 1
    assert report["pages"][0]["ocr_confidence_avg"] == 0.8


def test_tool_registry_executes_validated_tool_and_rejects_bad_arguments():
    registry = ToolRegistry()
    registry.register(
        ToolSpec("math.double", "double", {"value": "integer"}, "test"),
        lambda value: value * 2,
    )

    assert registry.execute("math.double", {"value": 4}) == 8
    import pytest

    with pytest.raises(ValueError):
        registry.execute("math.double", {"value": 4, "extra": True})
    with pytest.raises(TypeError):
        registry.execute("math.double", {"value": "4"})


def test_tool_registry_propagates_request_context_to_worker_thread():
    request_context = ContextVar("request_context", default="missing")
    registry = ToolRegistry()
    registry.register(
        ToolSpec("context.read", "read context", {}, "test"),
        request_context.get,
    )

    token = request_context.set("trace-context")
    try:
        assert registry.execute("context.read", {}) == "trace-context"
    finally:
        request_context.reset(token)


def test_tool_registry_enforces_scope_quota_and_approval(monkeypatch):
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "plugin.export",
            "export",
            {"user_id": "string"},
            "plugin-owner",
            required_scopes=frozenset({"export.read"}),
            quota_units=2,
            requires_approval=True,
        ),
        lambda user_id: user_id,
    )
    with pytest.raises(PermissionError, match="缺少权限范围"):
        registry.execute("plugin.export", {"user_id": "u1"}, trace_user_id="u1", principal_scopes=set())
    with pytest.raises(PermissionError, match="需要管理员审批"):
        registry.execute("plugin.export", {"user_id": "u1"}, trace_user_id="u1", principal_scopes={"export.read"})
    token = registry.approve("plugin.export", "u1", "admin")
    assert registry.execute(
        "plugin.export", {"user_id": "u1"}, trace_user_id="u1",
        principal_scopes={"export.read"}, approval_token=token,
    ) == "u1"
    day = datetime.now(timezone.utc).date().isoformat()
    registry._usage[("u1", day)] = (day, settings.agent_tool_daily_quota - 1)
    with pytest.raises(RuntimeError, match="配额已用尽"):
        registry.execute(
            "plugin.export", {"user_id": "u1"}, trace_user_id="u1",
            principal_scopes={"export.read"}, approval_token=token,
        )


def test_tool_registry_executes_subprocess_tools_with_json_contract():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "plugin.isolated",
            "isolated",
            {"value": "integer"},
            "plugin-owner",
            isolation_profile="subprocess",
        ),
        SubprocessTool((
            sys.executable,
            "-c",
            "import json,sys; value=json.load(sys.stdin); print(json.dumps({'value': value['value'] * 2}))",
        )),
    )
    assert registry.execute("plugin.isolated", {"value": 4}) == {"value": 8}


def test_tool_registry_deletes_local_user_governance_state():
    registry = ToolRegistry()
    registry.register(ToolSpec("plugin.read", "read", {}, "owner"), lambda: True)
    token = registry.approve("plugin.read", "u1", "admin")
    day = datetime.now(timezone.utc).date().isoformat()
    registry._usage[("u1", day)] = (day, 3)

    assert registry.delete_user_governance("u1") == 2
    assert token not in registry._approvals
    assert ("u1", day) not in registry._usage


def test_trace_store_redacts_sensitive_tool_arguments(tmp_path):
    store = AgentTraceStore(str(tmp_path / "redacted.sqlite3"))
    store.record("u1", "s1", "tool.knowledge.retrieve", "ok", {"query": "private text", "top_k": 4})

    payload = store.list_session("u1", "s1")[0]["payload"]
    assert payload["query"]["redacted"] is True
    assert payload["query"]["length"] == len("private text")
    assert payload["top_k"] == 4


def test_internal_token_rotation_keeps_previous_token_during_grace_period():
    state = InternalTokenState()
    state._current = "a" * 32

    status = state.rotate("b" * 32)

    assert state.accepts("a" * 32)
    assert state.accepts("b" * 32)
    assert status["previous_configured"] is True
    assert "b" * 8 not in status["current_fingerprint"]


def test_distilled_memory_preserves_provenance_without_message_content():
    with patch(
        "app.memory.distillation.long_term_memory.add_preference",
        return_value="mem_1",
    ) as add:
        apply_distilled_entries(
            "u1",
            [{
                "category": "preference",
                "content": "likes diagrams",
                "confidence": 0.9,
                "source_session_id": "s1",
                "evidence_hashes": ["abc123"],
            }],
        )

    add.assert_called_once_with(
        "u1",
        "likes diagrams",
        source_session_id="s1",
        evidence_hashes=["abc123"],
    )
