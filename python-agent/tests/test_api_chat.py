"""
集成测试：FastAPI TestClient 端到端测试

需要 langchain_community 正常导入，若环境不兼容自动跳过。

运行方式：
    pytest tests/test_api_chat.py -v -m integration
"""
import pytest

pytest.importorskip("langchain_community.document_loaders", reason="langchain_community 不可用，跳过集成测试")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.mark.integration
class TestHealthEndpoint:
    def test_health_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.integration
class TestSessionEndpoints:
    def test_list_sessions_empty(self):
        response = client.get("/api/v1/sessions?user_id=test_integration")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data

    def test_get_session_not_found(self):
        response = client.get("/api/v1/session/nonexistent_session_id")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []


@pytest.mark.integration
class TestMemoryEndpoints:
    def test_read_memory_empty(self):
        response = client.post("/api/v1/memory/read", json={
            "user_id": "test_integration",
            "memory_types": ["preference", "weak_point"]
        })
        assert response.status_code == 200
        data = response.json()
        assert "preferences" in data
        assert "weak_points" in data

    def test_write_and_confirm_preference(self):
        # 写入
        write_res = client.post("/api/v1/memory/write", json={
            "user_id": "test_integration",
            "entry": {
                "category": "preference",
                "content": "喜欢图表讲解",
                "topic": "",
                "confidence": 0.9
            }
        })
        assert write_res.status_code == 200
        assert write_res.json()["status"] == "success"

        # 确认已写入
        read_res = client.post("/api/v1/memory/read", json={
            "user_id": "test_integration",
            "memory_types": ["preference"]
        })
        prefs = read_res.json().get("preferences", [])
        assert any("图表" in p.get("content", "") for p in prefs)


@pytest.mark.integration
class TestKnowledgeEndpoints:
    def test_admin_collections(self):
        response = client.get("/api/v1/knowledge/admin/collections?user_id=test_integration")
        assert response.status_code == 200

    def test_admin_stats(self):
        response = client.get("/api/v1/knowledge/admin/stats")
        assert response.status_code == 200

    def test_search_no_results(self):
        response = client.get(
            "/api/v1/knowledge/search"
            "?query=test&user_id=test_integration&kb_id=nonexistent&top_k=3"
        )
        assert response.status_code == 200
        data = response.json()
        assert "chunks" in data
