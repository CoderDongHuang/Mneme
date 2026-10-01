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
    monkeypatch.setitem(main._rate_limit_store, "capacity-test", bucket)
    monkeypatch.setattr(main.time, "monotonic", lambda: 10.5)
    middleware = main.RateLimitMiddleware(lambda *_args: None)
    request = Request({"type": "http", "path": "/api/v1/knowledge/search",
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
