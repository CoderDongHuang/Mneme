"""Exercise real Redis deletion/readback in a disposable, dedicated Redis.

Run from python-agent with MNEME_SESSION_QA_REDIS_URL set. Never use the app's
Redis: this check owns fixed QA keys and flushes only its own temporary files.
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def main():
    url = os.environ["MNEME_SESSION_QA_REDIS_URL"]
    with tempfile.TemporaryDirectory(prefix="mneme-session-qa-") as directory:
        for name, relative in {
            "QDRANT_PATH": "qdrant", "CHROMA_PATH": "legacy-chroma", "SESSION_DATA_PATH": "sessions",
            "LEXICAL_INDEX_PATH": "lexical.sqlite3", "INDEX_GENERATION_PATH": "generations.sqlite3",
            "AGENT_TRACE_STORE_PATH": "traces.sqlite3", "MEMORY_VERSION_STORE_PATH": "versions.sqlite3",
        }.items():
            os.environ[name] = str(Path(directory) / relative)
        os.environ.update(MNEME_OFFLINE_EMBEDDINGS="true", VECTOR_STORE_MODE="local",
                          AUXILIARY_STORE_BACKEND="sqlite", DEEPSEEK_API_KEY="qa-dummy-key",
                          REDIS_HOST="127.0.0.1", REDIS_PORT="1", DASHSCOPE_API_KEY="qa-dummy-key")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import redis
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api import chat
        from app.memory.short_term_memory import session_persistence

        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1)
        assert client.ping()
        # A dedicated Redis is mandatory; refuse to touch any existing data.
        assert client.dbsize() == 0, "This check requires an empty disposable Redis"
        session_persistence._redis = client
        session_persistence._available = True
        session_persistence._last_attempt = time.monotonic()
        app = FastAPI()
        app.include_router(chat.router)
        http = TestClient(app, raise_server_exceptions=False)
        keys = ["mneme:session:11", "mneme:session:12", "mneme:session:22"]
        for key in keys:
            client.set(key, "isolated QA")
        chat.session_store._save("qa-alice", {"11": {"last_updated": "2000-01-01T00:00:00"}, "12": {}})
        chat.session_store._save("qa-bob", {"22": {}})
        try:
            # DEL may return normally without removing a key. Real EXISTS must
            # catch that and retain the file manifest, not acknowledge success.
            with patch.object(client, "delete", return_value=0):
                assert http.delete("/api/v1/admin/user/qa-alice").status_code == 500
            assert client.exists(*keys) == 3
            assert chat.session_store.cleanup_session_ids("qa-alice") == ["11", "12"]
            session_persistence._available = True
            with patch.object(client, "exists", side_effect=redis.ConnectionError("QA unavailable")):
                assert http.delete("/api/v1/admin/user/qa-alice").status_code == 500
            assert chat.session_store.cleanup_session_ids("qa-alice") == ["11", "12"]
            session_persistence._available = True
            assert http.delete("/api/v1/admin/user/qa-alice").status_code == 200
            assert client.exists(keys[0], keys[1]) == 0
            assert client.get(keys[2]) == "isolated QA"
            assert chat.session_store.cleanup_session_ids("qa-bob") == ["22"]
            # A missing optional JSON manifest cannot hide canonical MySQL IDs.
            client.set(keys[0], "isolated QA")
            request = {"session_ids": ["11", "12"]}
            for _ in range(2):
                result = http.post("/api/v1/admin/user/qa-alice/session-cache", json=request)
                assert result.json() == {"status": "verified", "checked_sessions": 2, "redis_sessions": 0}
            assert client.exists(keys[0], keys[1]) == 0
            assert client.get(keys[2]) == "isolated QA"
            print("PASS: real Redis no-op/read failure, retained manifest, retry, expired/missing metadata, tenant isolation and idempotence")
        finally:
            client.delete(*keys)
            assert client.dbsize() == 0
            client.close()


if __name__ == "__main__":
    main()
