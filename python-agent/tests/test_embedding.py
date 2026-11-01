import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.utils import embedding


def test_strict_real_embedding_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("MNEME_REQUIRE_REAL_EMBEDDINGS", "true")
    monkeypatch.setattr(
        embedding,
        "settings",
        SimpleNamespace(dashscope_api_key="configured", embedding_model="test"),
    )
    client = embedding.DashScopeEmbeddingFunction()
    monkeypatch.setattr(
        client,
        "_call_dashscope",
        lambda _texts: (_ for _ in ()).throw(ConnectionError("offline")),
    )

    with pytest.raises(RuntimeError, match="真实 Embedding API 调用失败"):
        client(["sample"])


def test_strict_real_embedding_requires_credential(monkeypatch):
    monkeypatch.setenv("MNEME_REQUIRE_REAL_EMBEDDINGS", "true")
    monkeypatch.setattr(
        embedding,
        "settings",
        SimpleNamespace(dashscope_api_key="", embedding_model="test"),
    )

    with pytest.raises(RuntimeError, match="有效 DASHSCOPE_API_KEY"):
        embedding.DashScopeEmbeddingFunction()(["sample"])


def test_provider_outage_never_silently_changes_vector_space(monkeypatch):
    client = embedding.DashScopeEmbeddingFunction()
    monkeypatch.delenv("MNEME_REQUIRE_REAL_EMBEDDINGS", raising=False)
    monkeypatch.setattr(client, "_should_use_offline", lambda: False)
    monkeypatch.setattr(client, "_call_dashscope", lambda _: (_ for _ in ()).throw(ConnectionError("provider unavailable")))
    with pytest.raises(RuntimeError, match="原有索引保留"):
        client(["existing document"])


@pytest.mark.parametrize("in_event_loop", [False, True], ids=["sync", "async-route"])
@pytest.mark.parametrize("delayed", [False, True, "drip"], ids=["success", "read-timeout", "slow-body"])
def test_real_http_transport_timeout_and_payload(monkeypatch, delayed, in_event_loop):
    """Exercise real HTTP, including the synchronous Qdrant callback bridge."""
    import dashscope

    received = []
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if delayed is True:
                release.wait(20)
                return
            body = json.dumps({"output": {"embeddings": [
                {"text_index": 0, "embedding": [0.5] * embedding.EMBEDDING_DIMENSION}
            ]}, "usage": {"total_tokens": 1}, "request_id": "local-qa"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if delayed == "drip":
                # Each read can succeed while the whole response exceeds the
                # budget. A requests read timeout alone would never stop this.
                for byte in body:
                    if release.is_set():
                        return
                    try:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    release.wait(0.05)
            else:
                self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(dashscope, "base_http_api_url", f"http://127.0.0.1:{server.server_port}/api/v1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.delenv("MNEME_REQUIRE_REAL_EMBEDDINGS", raising=False)
    monkeypatch.setattr(embedding, "settings", SimpleNamespace(
        dashscope_api_key="local-test-only", embedding_model="text-embedding-v3", demo_mode=False,
    ))
    client = embedding.DashScopeEmbeddingFunction()
    monkeypatch.setattr(client, "_should_use_offline", lambda: False)
    async def from_route():
        return client(["local transport test"])

    def invoke():
        return asyncio.run(from_route()) if in_event_loop else client(["local transport test"])

    started = time.monotonic()
    try:
        if delayed:
            with pytest.raises(RuntimeError, match="原有索引保留") as error:
                invoke()
            assert isinstance(error.value.__cause__, TimeoutError)
            assert 8 <= time.monotonic() - started < 18
        else:
            assert invoke() == [[0.5] * embedding.EMBEDDING_DIMENSION]
        assert len(received) == 1
        assert received[0]["input"]["texts"] == ["local transport test"]
        assert "timeout" not in received[0].get("parameters", {})
        assert "request_timeout" not in received[0].get("parameters", {})
        assert not any(t.name.startswith("mneme-embedding") for t in threading.enumerate())
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
