from app.agents.trace_store import AgentTraceStore
from app.api.chat import _visual_region
from app.api.chat_stream import _source_payload
from app.memory.version_store import MemoryVersionStore
from app.tools.registry import tool_registry


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
