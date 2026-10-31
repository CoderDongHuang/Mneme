"""Measure delivered ASGI responses, including streaming and cancellation."""

import asyncio
from time import perf_counter
import uuid

from prometheus_client import Counter, Histogram

from app.core.logging import setup_logger, trace_id_var


logger = setup_logger("http_lifecycle")
BUCKETS = (0.01, 0.05, 0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)
REQUEST_COUNT = Counter("mneme_python_http_requests_total", "HTTP requests", ["method", "path", "status"])
REQUEST_DURATION = Histogram(
    "mneme_python_http_request_duration_seconds", "Full HTTP response lifetime including body and cleanup",
    ["method", "path"], buckets=BUCKETS,
)
RESPONSE_HEADERS = Histogram(
    "mneme_python_http_response_headers_seconds", "Time until response headers are delivered",
    ["method", "path"], buckets=BUCKETS,
)
STREAM_DURATION = Histogram(
    "mneme_python_sse_duration_seconds", "SSE lifetime until completion or interruption",
    ["path", "outcome", "reason"], buckets=BUCKETS,
)
STREAM_TTFT = Histogram(
    "mneme_python_sse_ttft_seconds", "Time until first answer token event is delivered (not meta or headers)",
    ["path"], buckets=BUCKETS,
)
ANSWER_DURATION = Histogram(
    "mneme_python_sse_answer_duration_seconds", "Time until terminal answer event is delivered, including preparation",
    ["path", "event"], buckets=BUCKETS,
)
STREAM_ENDS = Counter(
    "mneme_python_sse_ends_total", "SSE terminal outcomes; interrupted streams remain observable",
    ["path", "outcome", "reason"],
)
REASONS = {"model_timeout", "model_error", "grounding_failed", "memory_failed", "user_stopped"}


def metric_path(request) -> str:
    """Route templates keep resource identifiers out of metric labels/logs."""
    return getattr(request.scope.get("route"), "path", None) or "unmatched"


class EventNames:
    """Read only bounded event headers, never buffer answer data or parse JSON."""

    def __init__(self):
        self.pending = b""
        self.event = b""
        self.data = False
        self.line_length = 0

    def feed(self, body: bytes):
        position = 0
        while position < len(body):
            end = body.find(b"\n", position)
            part = body[position:] if end < 0 else body[position:end]
            # Only event names are retained; data lines use a six-byte prefix.
            if len(self.pending) < 128:
                self.pending = (self.pending + part[:128])[:128]
                if self.pending.startswith(b"data:"):
                    self.pending = self.pending[:6]
                    value_start = max(0, 5 - self.line_length)
                    self.data = self.data or bool(part[value_start:].strip(b" \t\r"))
            self.line_length += len(part)
            if end < 0:
                break
            if self.line_length <= 128 and self.pending.startswith(b"event:"):
                self.event = self.pending[6:].strip()
            if self.pending in (b"", b"\r"):
                if self.event and self.data:
                    yield self.event
                self.event = b""
                self.data = False
            self.pending = b""
            self.line_length = 0
            position = end + 1


class TraceAndLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-trace-id", b"")
        trace_id = supplied.decode("ascii", errors="ignore") if len(supplied) <= 128 else ""
        if not trace_id or not all(char.isalnum() or char in "-_." for char in trace_id):
            trace_id = uuid.uuid4().hex
        token = trace_id_var.set(trace_id)
        started = perf_counter()
        status = 500
        streaming = False
        finished = False
        disconnected = False
        failure = None
        terminal = None
        first_token = False
        parser = EventNames()

        async def observed_receive():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def observed_send(message):
            nonlocal status, streaming, finished, first_token, terminal, failure
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = [(key, value) for key, value in message.get("headers", []) if key.lower() != b"x-trace-id"]
                streaming = any(key.lower() == b"content-type" and value.lower().startswith(b"text/event-stream") for key, value in response_headers)
                message = {**message, "headers": [*response_headers, (b"x-trace-id", trace_id.encode("ascii"))]}
            try:
                await send(message)
            except OSError:
                failure = "transport_error"
                raise
            elapsed = perf_counter() - started
            path = getattr(scope.get("route"), "path", None) or "unmatched"
            if message["type"] == "http.response.start":
                RESPONSE_HEADERS.labels(scope["method"], path).observe(elapsed)
            elif message["type"] == "http.response.body":
                if streaming:
                    for event in parser.feed(message.get("body", b"")):
                        if event == b"token" and not first_token:
                            first_token = True
                            STREAM_TTFT.labels(path).observe(elapsed)
                        if event in (b"done", b"error") and terminal is None:
                            terminal = event.decode("ascii")
                            ANSWER_DURATION.labels(path, terminal).observe(elapsed)
                finished = not message.get("more_body", False)

        try:
            await self.app(scope, observed_receive, observed_send)
        except asyncio.CancelledError:
            failure = failure or "cancelled"
            raise
        except Exception:
            failure = failure or "error"
            raise
        finally:
            elapsed = perf_counter() - started
            path = getattr(scope.get("route"), "path", None) or "unmatched"
            try:
                REQUEST_COUNT.labels(scope["method"], path, status).inc()
                REQUEST_DURATION.labels(scope["method"], path).observe(elapsed)
                if streaming:
                    if finished and terminal == "done" and failure is None:
                        outcome = "completed"
                    elif disconnected:
                        outcome = "client_disconnect"
                    elif failure:
                        outcome = failure
                    elif terminal == "error":
                        outcome = "error"
                    elif status >= 400:
                        outcome = "http_error"
                    else:
                        outcome = "incomplete"
                    reason = scope.get("mneme.stream.reason")
                    reason = reason if reason in REASONS else outcome
                    STREAM_ENDS.labels(path, outcome, reason).inc()
                    STREAM_DURATION.labels(path, outcome, reason).observe(elapsed)
                logger.info("%s %s status=%s (%.0fms)", scope["method"], path, status, elapsed * 1000)
            finally:
                trace_id_var.reset(token)
