"""Exercise both HTTP paths against shared, language-independent wire fixtures."""
import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
import pytest

from main import app

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "contracts/citation-regions.json").read_text(encoding="utf-8"))


def test_generated_schema_examples_and_browser_types_are_current():
    subprocess.run([sys.executable, str(ROOT / "python-agent/scripts/export_chat_contract.py"), "--check"], check=True)


@pytest.mark.parametrize("case", CASES)
def test_json_and_sse_share_source_wire_contract(monkeypatch, case):
    import app.api.chat as sync_api
    import app.api.chat_stream as stream_api
    chunks = [
        {"content": "", "metadata": {"source": "empty.txt"}},
        {"content": "evidence [2]", "score": 0.91, "retrieval_ranks": {"bm25": 1},
         "metadata": {"document_id": 42, "source": "report.pdf", "page": 2,
                      "visual_region": case["input"], "content_sha256": "file-version",
                      "evidence_type": "visual", "ocr_confidence": 0.88}},
    ]

    async def model(*_):
        yield AIMessageChunk(content="Answer [2]")

    for module in [sync_api, stream_api]:
        monkeypatch.setattr(module, "prepare_conversation", lambda _: {"intent": "general", "retrieved_chunks": chunks})
        monkeypatch.setattr(module, "build_llm_prompt", lambda _: "prompt")
        monkeypatch.setattr(module, "complete_conversation", lambda *args: {})
        monkeypatch.setattr(module.llm, "invoke", lambda *_: AIMessageChunk(content="Answer [2]"))
        monkeypatch.setattr(module.llm, "astream", model)

    request = {"user_id": "citation-contract", "session_id": "contract", "message": "question"}
    with TestClient(app) as client:
        sync = client.post("/api/v1/chat", json=request)
        stream = client.post("/api/v1/chat/stream", json=request)
    assert sync.status_code == stream.status_code == 200
    assert "event: done" in stream.text
    events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
    sources = sync.json()["sources"]
    assert sources == events[0]["sources"]
    assert [source["document_name"] for source in sources] == ["empty.txt", "report.pdf"]
    assert sources[0]["chunk_content"] == ""
    assert sources[0]["visual_region"] is None
    assert sources[1]["visual_region"] == case["expected"]
    assert sources[1]["document_id"] == "42"
    assert sources[1]["content_sha256"] == "file-version"
    assert sources[1]["retrieval_ranks"] == {"bm25": 1}
    assert sources[1]["visual_page"] == 2
    assert sources[1]["ocr_confidence"] == 0.88
