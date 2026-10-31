import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from prometheus_client import REGISTRY

from app.core import http_metrics as metrics
from app.core.logging import trace_id_var


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0


def scope(path):
    return {"type": "http", "method": "POST", "headers": [(b"x-trace-id", b"test-stream-trace")],
            "route": SimpleNamespace(path=path)}


def test_duration_includes_final_body_and_cleanup_and_ttft_ignores_meta(monkeypatch):
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(metrics, "perf_counter", lambda: clock.now)
    path = "/metric-test/{session}"
    headers = []

    async def send(message):
        if message["type"] == "http.response.start":
            headers.extend(message["headers"])

    async def application(scope, receive, send):
        assert trace_id_var.get() == "test-stream-trace"
        clock.now = .2
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        clock.now = 1
        await send({"type": "http.response.body", "body": b'event: meta\ndata: {}\n\n', "more_body": True})
        clock.now = 2
        await send({"type": "http.response.body", "body": b'event: tok', "more_body": True})
        clock.now = 3
        await send({"type": "http.response.body", "body": b'en\ndata: {"content":"a"}\n\n', "more_body": True})
        clock.now = 30
        await send({"type": "http.response.body", "body": b'event: done\ndata: {}\n\n', "more_body": True})
        clock.now = 31
        await send({"type": "http.response.body", "body": b'', "more_body": False})
        clock.now = 32

    async def run():
        token = trace_id_var.set("outer")
        try:
            await metrics.TraceAndLoggingMiddleware(application)(scope(path), None, send)
            assert trace_id_var.get() == "outer"
        finally:
            trace_id_var.reset(token)
    asyncio.run(run())
    assert (b"x-trace-id", b"test-stream-trace") in headers
    assert sample("mneme_python_http_response_headers_seconds_sum", method="POST", path=path) == .2
    assert sample("mneme_python_http_request_duration_seconds_sum", method="POST", path=path) == 32
    assert sample("mneme_python_sse_ttft_seconds_sum", path=path) == 3
    assert sample("mneme_python_sse_answer_duration_seconds_sum", path=path, event="done") == 30
    assert sample("mneme_python_sse_duration_seconds_sum", path=path, outcome="completed", reason="completed") == 32


@pytest.mark.parametrize("mode,outcome,reason", [
    ("disconnect", "client_disconnect", "client_disconnect"),
    ("send", "transport_error", "transport_error"),
    ("cancel", "cancelled", "cancelled"),
    ("raise", "error", "error"),
    ("error", "error", "memory_failed"),
    ("timeout", "completed", "model_timeout"),
    ("incomplete", "incomplete", "incomplete"),
])
def test_stream_termination_records_one_bounded_outcome(mode, outcome, reason):
    path = "/metric-termination/" + mode
    before = sample("mneme_python_sse_ends_total", path=path, outcome=outcome, reason=reason)

    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream; charset=utf-8")]})
        scope["mneme.stream.reason"] = "untrusted-user-value"
        if mode == "disconnect":
            await receive()
            return
        if mode == "cancel":
            raise asyncio.CancelledError()
        if mode == "raise":
            raise ValueError("private message")
        if mode == "error":
            scope["mneme.stream.reason"] = "memory_failed"
            body = b'event: error\ndata: {}\n\n'
        elif mode == "timeout":
            scope["mneme.stream.reason"] = "model_timeout"
            body = b'event: done\ndata: {}\n\n'
        else:
            body = b'event: token\ndata: {}\n\n'
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def send(message):
        if mode == "send" and message["type"] == "http.response.body":
            raise OSError("socket closed")

    async def receive():
        return {"type": "http.disconnect"}

    expected = {"send": OSError, "cancel": asyncio.CancelledError, "raise": ValueError}.get(mode)
    with pytest.raises(expected) if expected else nullcontext():
        asyncio.run(metrics.TraceAndLoggingMiddleware(application)(scope(path), receive, send))
    assert sample("mneme_python_sse_ends_total", path=path, outcome=outcome, reason=reason) == before + 1
    if mode != "timeout":
        assert sample("mneme_python_sse_ends_total", path=path, outcome="completed", reason="completed") == 0


def test_sse_header_parser_handles_fragmentation_crlf_large_data_and_empty_events():
    parser = metrics.EventNames()
    events = []
    body = b'event: meta\r\ndata: {}\r\n\r\nevent: token\r\ndata: ' + b'a' * 10000 + b'\r\n\r\nevent: done\ndata: {}\n\n'
    for index in range(0, len(body), 3):
        events.extend(parser.feed(body[index:index + 3]))
        assert len(parser.pending) <= 128
    assert events == [b"meta", b"token", b"done"]
    assert list(parser.feed(b"event: token\ndata: \n\n")) == []


@pytest.mark.parametrize("interrupt", [False, True])
def test_real_tcp_thirty_second_sse_or_early_disconnect(interrupt):
    import socket
    import threading
    import time

    import httpx
    import uvicorn
    from fastapi import FastAPI
    from app.api.chat_stream import ClosingStreamingResponse

    app = FastAPI()
    app.add_middleware(metrics.TraceAndLoggingMiddleware)
    path = "/tcp-metric-interrupt" if interrupt else "/tcp-metric-thirty-seconds"
    released = threading.Event()

    async def endpoint():
        async def generate():
            try:
                yield 'event: meta\ndata: {}\n\n'
                await asyncio.sleep(.1)
                yield 'event: token\ndata: {"content":"answer"}\n\n'
                await asyncio.sleep(30)
                yield 'event: done\ndata: {}\n\n'
            finally:
                released.set()
        return ClosingStreamingResponse(generate(), media_type="text/event-stream")

    app.add_api_route(path, endpoint)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        with httpx.Client(trust_env=False, timeout=40) as client:
            with client.stream("GET", f"http://127.0.0.1:{sock.getsockname()[1]}{path}") as response:
                for line in response.iter_lines():
                    if interrupt and line == "event: token":
                        break
        assert released.wait(2)
        outcome = "client_disconnect" if interrupt else "completed"
        deadline = time.monotonic() + 2
        while sample("mneme_python_sse_ends_total", path=path, outcome=outcome, reason=outcome) == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        assert sample("mneme_python_sse_ends_total", path=path, outcome=outcome, reason=outcome) == 1
        full = sample("mneme_python_http_request_duration_seconds_sum", method="GET", path=path)
        ttft = sample("mneme_python_sse_ttft_seconds_sum", path=path)
        assert .08 < ttft < 3
        assert full >= ttft
        if interrupt:
            assert time.monotonic() - started < 5
        else:
            assert 30 <= full < 36
            assert sample("mneme_python_sse_answer_duration_seconds_sum", path=path, event="done") >= 30
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
