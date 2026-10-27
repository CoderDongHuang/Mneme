import json
from unittest.mock import Mock, AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk
from fastapi.testclient import TestClient
from main import app
from app.knowledge.citations import NO_EVIDENCE_ANSWER, INVALID_EVIDENCE_ANSWER


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("answer,expected", [("fabricated [7]", INVALID_EVIDENCE_ANSWER), ("A [1] and B [2]", "A [1] and B [2]")])
def test_sync_and_sse_validate_identical_references(monkeypatch, stream, answer, expected):
    import app.api.chat as sync_api
    import app.api.chat_stream as stream_api
    module = stream_api if stream else sync_api
    state = {"intent": "qa", "retrieved_chunks": [
        {"content": "first evidence", "retrieval_ranks": {"dense:0": 2, "bm25": 1}, "metadata": {"document_id": "a", "source": "A", "content_sha256": "version-a"}},
        {"content": "second evidence", "metadata": {"document_id": "b", "source": "B"}},
    ]}
    monkeypatch.setattr(module, "prepare_conversation", lambda _: state)
    monkeypatch.setattr(module, "build_llm_prompt", lambda _: "prompt")
    monkeypatch.setattr(module, "complete_conversation", lambda *args: {})
    monkeypatch.setattr(module.llm, "invoke", lambda *_: AIMessageChunk(content=answer))
    monkeypatch.setattr(module.llm, "ainvoke", AsyncMock(return_value=AIMessageChunk(content=json.dumps({
        "checks": [{"id": 0, "supported": True, "quotes": [
            {"citation": 1, "text": "first evidence"}, {"citation": 2, "text": "second evidence"}]}]}))))

    async def model(*_):
        yield AIMessageChunk(content=answer[:5])
        yield AIMessageChunk(content=answer[5:])

    monkeypatch.setattr(module.llm, "astream", model)
    client = TestClient(app)
    response = client.post("/api/v1/chat/stream" if stream else "/api/v1/chat", json={
        "user_id": "evidence-test", "session_id": "evidence-session", "message": "compare"})
    assert response.status_code == 200
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert events[0]["sources"][1]["document_id"] == "b"
        assert events[0]["sources"][0]["retrieval_ranks"] == {"dense:0": 2, "bm25": 1}
        assert "".join(item.get("content", "") for item in events) == expected
        assert "fabricated" not in response.text
    else:
        assert response.json()["answer"] == expected
        assert response.json()["sources"][1]["document_id"] == "b"
        assert response.json()["sources"][0]["content_sha256"] == "version-a"


@pytest.mark.parametrize("stream", [False, True])
def test_no_evidence_refuses_without_calling_provider(monkeypatch, stream):
    import app.api.chat as sync_api
    import app.api.chat_stream as stream_api
    module = stream_api if stream else sync_api
    monkeypatch.setattr(module, "prepare_conversation", lambda _: {"intent": "qa"})
    monkeypatch.setattr(module, "build_llm_prompt", lambda _: "prompt")
    monkeypatch.setattr(module, "complete_conversation", lambda *args: {})
    provider = Mock(side_effect=AssertionError("must not call provider"))
    monkeypatch.setattr(module.llm, "invoke", provider)
    monkeypatch.setattr(module.llm, "astream", provider)
    response = TestClient(app).post("/api/v1/chat/stream" if stream else "/api/v1/chat", json={
        "user_id": "evidence-test", "session_id": "evidence-session", "message": "unknown"})
    assert NO_EVIDENCE_ANSWER in response.text
    provider.assert_not_called()
