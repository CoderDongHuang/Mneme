from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.memory.memory_store import memory_store
from main import app


def test_memory_profile_mismatch_returns_actionable_conflict_without_writing(monkeypatch):
    collection = Mock()
    collection.metadata = {"embedding_profile": "legacy-profile"}
    collection.count.return_value = 1
    monkeypatch.setattr(memory_store, "_collection", collection)
    response = TestClient(app).post("/api/v1/memory/write", json={
        "user_id": "profile-conflict-user",
        "entry": {"category": "preference", "content": "先核验原文"},
    })
    assert response.status_code == 409
    assert response.json()["code"] == "MEMORY_INDEX_MIGRATION_REQUIRED"
    assert "迁移" in response.json()["detail"]
    collection.add.assert_not_called()
    collection.modify.assert_not_called()
