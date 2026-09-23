import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.models.chat import ChatRequest
from main import app


def test_chat_request_limits_message_and_knowledge_bases():
    with pytest.raises(ValidationError):
        ChatRequest(user_id="u", session_id="s", message="x" * 8001)
    with pytest.raises(ValidationError):
        ChatRequest(
            user_id="u",
            session_id="s",
            message="hello",
            knowledge_base_ids=[str(i) for i in range(21)],
        )
    with pytest.raises(ValidationError):
        ChatRequest(
            user_id="u",
            session_id="s",
            message="hello",
            knowledge_base_ids=["x" * 129],
        )


def test_chat_request_strips_knowledge_base_ids():
    request = ChatRequest(
        user_id="u", session_id="s", message="hello", knowledge_base_ids=[" kb-1 "]
    )
    assert request.knowledge_base_ids == ["kb-1"]


def test_chat_endpoints_reject_oversized_raw_bodies():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            content=b"{" + b" " * (64 * 1024) + b"}",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
