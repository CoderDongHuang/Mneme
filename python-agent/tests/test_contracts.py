from fastapi.testclient import TestClient

from main import app
from main import settings


def test_openapi_contains_durable_ingestion_contract():
    schema = TestClient(app).get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/knowledge/internal/ingest"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]
    assert "200" in operation["responses"]


def test_chat_contract_exposes_request_id():
    schema = TestClient(app).get("/openapi.json").json()
    chat_schema = schema["components"]["schemas"]["ChatRequest"]
    assert "request_id" in chat_schema["properties"]


def test_internal_routes_reject_missing_service_token():
    old_skip = settings.skip_internal_auth
    old_token = settings.internal_service_token
    object.__setattr__(settings, "skip_internal_auth", False)
    object.__setattr__(settings, "internal_service_token", "test-internal-token")
    try:
        client = TestClient(app)
        assert (
            client.post(
                "/api/v1/memory/read", json={"user_id": "1", "memory_types": []}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/memory/read",
                headers={"X-Internal-Service-Token": "test-internal-token"},
                json={"user_id": "1", "memory_types": []},
            ).status_code
            == 200
        )
    finally:
        object.__setattr__(settings, "skip_internal_auth", old_skip)
        object.__setattr__(settings, "internal_service_token", old_token)
