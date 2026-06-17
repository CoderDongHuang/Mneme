"""
集成测试：FastAPI TestClient 端到端测试

自动检测全部依赖，缺任何依赖都安全跳过，不会因缺少非测试依赖而中断 CI。

运行方式：
    pytest tests/test_api_chat.py -v -m integration
"""
import pytest

# 安全导入：缺任何依赖都跳过，不让 CI 中断
try:
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
except ImportError as e:
    pytest.skip(f"缺少依赖，跳过集成测试: {e}", allow_module_level=True)


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
        import uuid
        from datetime import datetime
        now = datetime.now().isoformat()

        # 写入 — 完整 MemoryEntry 字段
        entry = {
            "id": f"mem_test_{uuid.uuid4().hex[:8]}",
            "content": "喜欢图表讲解",
            "category": "preference",
            "topic": "图表",
            "importance_score": 0.9,
            "created_at": now,
            "updated_at": now,
        }
        write_res = client.post("/api/v1/memory/write", json={
            "user_id": "test_integration",
            "entry": entry
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
