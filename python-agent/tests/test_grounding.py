import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.knowledge import grounding


def state():
    return {"intent": "qa", "message": "What is the release date?", "retrieved_chunks": [
        {"content": "The release is October 27. The old date was October 20."},
        {"content": "The project supports private deployments only."}]}


def run(monkeypatch, answer, verdict=None, error=None):
    monkeypatch.setattr(grounding, "settings", replace(grounding.settings, demo_mode=False, deterministic_test_llm=False))
    invoke = AsyncMock(side_effect=error, return_value=AIMessage(content=json.dumps(verdict)))
    result = asyncio.run(grounding.verify_evidence_answer(state(), answer, invoke))
    return result, invoke


def test_supported_claim_requires_literal_quote_and_the_correct_reference(monkeypatch):
    answer = "Release is October 27 [1]."
    verdict = {"checks": [{"id": 0, "supported": True, "quotes": [{"citation": 1, "text": "release is October 27"}]}]}
    result, _ = run(monkeypatch, answer, verdict)
    assert result == answer
    verdict["checks"][0]["quotes"][0]["citation"] = 2
    assert run(monkeypatch, answer, verdict)[0] == grounding.UNSUPPORTED_ANSWER


@pytest.mark.parametrize("checks", [[],
    [{"id": 0, "supported": False, "quotes": []}],
    [{"id": 0, "supported": True, "quotes": [{"citation": 1, "text": "invented quote"}]}],
    [{"id": 0, "supported": True, "quotes": []}],
    [{"id": 99, "supported": True, "quotes": []}],
])
def test_omitted_unsupported_or_fabricated_evidence_fails_closed(monkeypatch, checks):
    assert run(monkeypatch, "Release is tomorrow [1].", {"checks": checks})[0] == grounding.UNSUPPORTED_ANSWER


def test_judge_cannot_silently_omit_a_second_claim(monkeypatch):
    verdict = {"checks": [{"id": 0, "supported": True, "quotes": [{"citation": 1, "text": "October 27"}]}]}
    assert run(monkeypatch, "Release is October 27 [1].\nIt is public [2].", verdict)[0] == grounding.UNSUPPORTED_ANSWER


def test_verification_outage_refuses_and_does_not_expose_provider_error(monkeypatch):
    result, _ = run(monkeypatch, "Release date [1].", error=TimeoutError("private-key"))
    assert result == grounding.UNSUPPORTED_ANSWER and "private-key" not in result


def test_refusal_is_allowed_without_asking_a_model_to_invent_evidence(monkeypatch):
    answer = grounding.NO_EVIDENCE_ANSWER
    result, invoke = run(monkeypatch, answer)
    assert result == answer
    invoke.assert_not_called()


@pytest.mark.parametrize("stream", [False, True])
def test_unsupported_claim_never_leaks_from_sync_or_sse(monkeypatch, stream):
    from fastapi.testclient import TestClient
    from main import app
    import app.api.chat as sync_api
    import app.api.chat_stream as stream_api
    from langchain_core.messages import AIMessageChunk
    module = stream_api if stream else sync_api
    monkeypatch.setattr(grounding, "settings", replace(grounding.settings, demo_mode=False, deterministic_test_llm=False))
    monkeypatch.setattr(module, "prepare_conversation", lambda _: state())
    monkeypatch.setattr(module, "build_llm_prompt", lambda _: "synthetic")
    monkeypatch.setattr(module, "complete_conversation", lambda *args: {})
    monkeypatch.setattr(module.llm, "invoke", lambda *_: AIMessage(content="Secret false claim [1]."))
    monkeypatch.setattr(module.llm, "ainvoke", AsyncMock(return_value=AIMessage(content='{"checks":[{"id":0,"supported":false,"quotes":[]}]}')))
    async def generate(*args):
        yield AIMessageChunk(content="Secret false claim [1].")
    monkeypatch.setattr(module.llm, "astream", generate)
    result = TestClient(app).post("/api/v1/chat/stream" if stream else "/api/v1/chat", json={
        "user_id": "grounding", "session_id": "grounding-session", "message": "release date"})
    assert grounding.UNSUPPORTED_ANSWER in result.text
    assert "Secret false claim" not in result.text
