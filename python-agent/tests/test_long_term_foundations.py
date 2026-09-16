from app.agents.trace_store import AgentTraceStore
from app.api.chat import _visual_region
from app.api.chat_stream import _source_payload
from app.api.knowledge import document_report
from app.memory.version_store import MemoryVersionStore
from app.tools.registry import ToolRegistry, ToolSpec, tool_registry
from app.core.internal_tokens import InternalTokenState
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
