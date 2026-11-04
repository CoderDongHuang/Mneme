import asyncio
import threading
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.api import knowledge
from app.core.config import _positive_float
import main


@pytest.mark.parametrize("value", ["nan", "inf", "0", "-1"])
def test_invalid_internal_rate_limit_rejected(monkeypatch, value):
    monkeypatch.setenv("TEST_RATE_LIMIT", value)
    with pytest.raises(ValueError, match="finite and positive"):
        _positive_float("TEST_RATE_LIMIT", 1)


def test_rate_limit_uses_configured_burst_and_refill(monkeypatch):
    monkeypatch.setattr(main, "settings", SimpleNamespace(
        internal_rate_limit_burst=2, internal_rate_limit_per_second=4,
    ))
    bucket = {"tokens": 0.0, "last": 10.0}
    monkeypatch.setitem(main._rate_limit_store, ("capacity-test", "service"), bucket)
    monkeypatch.setattr(main.time, "monotonic", lambda: 10.5)
    middleware = main.RateLimitMiddleware(lambda *_args: None)
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/knowledge/search",
                       "client": ("capacity-test", 1), "headers": []})
    calls = []

    async def call_next(_request):
        calls.append(True)
        return "accepted"

    async def exercise():
        assert await middleware.dispatch(request, call_next) == "accepted"
        assert await middleware.dispatch(request, call_next) == "accepted"
        assert (await middleware.dispatch(request, call_next)).status_code == 429

    asyncio.run(exercise())
    assert len(calls) == 2


def test_background_saturation_does_not_starve_inference(monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "settings", SimpleNamespace(
        internal_rate_limit_burst=2, internal_rate_limit_per_second=0.25,
        skip_internal_auth=False,
    ))
    monkeypatch.setattr(main, "_rate_limit_store", main.defaultdict(
        lambda: {"tokens": 2, "last": 10.0},
    ))
    monkeypatch.setattr(main.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(main.internal_tokens, "accepts", lambda value: value == "trusted-test-token")
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST", "DELETE", "PATCH"])
    async def endpoint(path: str):
        if path == "api/v1/chat/stream":
            return StreamingResponse(iter([b'event: done\ndata: {"ok":true}\n\n']),
                                     media_type="text/event-stream")
        return {"ok": True}

    app.add_middleware(main.RateLimitMiddleware)
    app.add_middleware(main.InternalServiceAuthMiddleware)
    client = TestClient(app)
    headers = {"X-Internal-Service-Token": "trusted-test-token"}
    # An untrusted request cannot consume any budget or create a new one.
    assert client.post("/api/v1/chat/stream").status_code == 401
    assert not main._rate_limit_store
    assert client.delete("/api/v1/memory/admin/user/1", headers=headers).status_code == 200
    assert client.get("/api/v1/admin/user/1/deletion-report", headers=headers).status_code == 200
    blocked = client.get("/api/v1/admin/user/2/deletion-report", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "4"
    # Real background cleanup must not starve ordinary reads or saved edits.
    assert client.get("/api/v1/memory/admin/3", headers=headers).status_code == 200
    assert client.patch("/api/v1/memory/admin/mem_3", headers=headers).status_code == 200
    assert client.get("/api/v1/agent/privacy/2", headers=headers).status_code == 429
    # Different URLs, methods and spoofed user headers cannot reset service capacity.
    assert client.get("/arbitrary-new-route", headers={**headers, "X-User-Id": "3"}).status_code == 429
    stream = client.post("/api/v1/chat/stream", headers=headers)
    assert stream.status_code == 200
    assert 'event: done' in stream.text
    assert client.post("/api/v1/chat", headers=headers).status_code == 200
    # Sync, SSE and quiz calls share the bounded inference budget.
    assert client.post("/api/v1/knowledge/quiz/generate", headers=headers).status_code == 429
    assert len(main._rate_limit_store) == 3
    # Every class retains protection and refills using the configured rate.
    monkeypatch.setattr(main.time, "monotonic", lambda: 14.0)
    assert client.post("/api/v1/knowledge/quiz/generate", headers=headers).status_code == 200
    assert client.get("/api/v1/admin/user/1/deletion-report", headers=headers).status_code == 200
    assert client.patch("/api/v1/memory/admin/mem_3", headers=headers).status_code == 200


@pytest.mark.parametrize(('method', 'path', 'maintenance'), [
    ('DELETE', '/api/v1/admin/user/1', True),
    ('DELETE', '/api/v1/session/1', True),
    ('DELETE', '/api/v1/memory/admin/user/1', True),
    ('DELETE', '/api/v1/knowledge/admin/user/1', True),
    ('DELETE', '/api/v1/knowledge/admin/collections/1', True),
    ('DELETE', '/api/v1/knowledge/admin/documents/1', True),
    ('DELETE', '/api/v1/knowledge/internal/cancelled-documents/1', True),
    ('POST', '/api/v1/admin/user/1/session-cache', True),
    ('GET', '/api/v1/admin/user/1/deletion-report', True),
    ('GET', '/api/v1/knowledge/admin/deletion-report', True),
    ('GET', '/api/v1/admin/user/1', False),
    ('PATCH', '/api/v1/memory/admin/user/1', False),
    ('GET', '/api/v1/admin/user/1/deletion-report/extra', False),
    ('GET', '/api/v1/knowledge/admin/deletion-report-extra', False),
    ('DELETE', '/api/v1/session/1/extra', False),
    ('POST', '/api/v1/admin/user/1/session-cache/extra', False),
    ('DELETE', '/api/v1/memory/admin/mem_1', False),
])
def test_maintenance_budget_is_fixed_and_requires_exact_route_and_method(monkeypatch, method, path, maintenance):
    monkeypatch.setattr(main, 'settings', SimpleNamespace(
        internal_rate_limit_burst=2, internal_rate_limit_per_second=1,
    ))
    monkeypatch.setattr(main, '_rate_limit_store', main.defaultdict(
        lambda: {'tokens': 2, 'last': 10.0},
    ))
    monkeypatch.setattr(main.time, 'monotonic', lambda: 10.0)
    middleware = main.RateLimitMiddleware(lambda *_args: None)
    request = Request({'type': 'http', 'method': method, 'path': path,
                       'client': ('gateway', 1), 'headers': [(b'x-user-id', b'new-budget')]})

    async def next_call(_request):
        return 'accepted'

    assert asyncio.run(middleware.dispatch(request, next_call)) == 'accepted'
    assert list(main._rate_limit_store) == [('gateway', 'maintenance' if maintenance else 'service')]


def test_retrieval_runs_outside_event_loop_thread(monkeypatch):
    loop_thread = threading.get_ident()
    threads = []

    def retrieve(*_args):
        threads.append(threading.get_ident())
        return []

    monkeypatch.setattr(knowledge, "retrieve", retrieve)
    result = asyncio.run(knowledge.search("query", "user", "kb", 3))
    assert result.chunks == []
    assert threads and threads[0] != loop_thread
