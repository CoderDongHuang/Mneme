import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.api import models
from app.core.user_model import UserModelMiddleware


def test_personal_model_test_receipt_matches_the_shared_rest_example(monkeypatch):
    from app.core import internal_tokens

    monkeypatch.setattr(internal_tokens.internal_tokens, "accepts", lambda supplied: supplied == "trusted")
    monkeypatch.setattr(models.llm, "ainvoke", AsyncMock(return_value=AIMessage(content="OK")))
    app = FastAPI()
    app.add_middleware(UserModelMiddleware)
    app.include_router(models.router)
    config = {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "apiKey": "synthetic-test-secret",
        "baseUrl": "https://api.openai.com/v1",
    }
    encoded = base64.b64encode(json.dumps(config).encode()).decode()

    with TestClient(app) as client:
        response = client.post("/api/v1/models/test", headers={
            "X-Internal-Service-Token": "trusted",
            "X-Mneme-Model": encoded,
        })

    cases_path = Path(__file__).resolve().parents[2] / "contracts" / "settings-model.cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    example = next(case["data"] for case in cases if case["id"] == "model-test-receipt")
    receipt = response.json()
    assert response.status_code == 200
    assert set(receipt) == set(example)
    assert {key: receipt[key] for key in ("status", "model", "provider")} == {
        "status": "ok", "model": "gpt-4.1-mini", "provider": "openai",
    }
    assert isinstance(receipt["latency_ms"], int)
    assert receipt["latency_ms"] >= 0
    assert "apiKey" not in receipt
