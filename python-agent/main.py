import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from fastapi.responses import Response

from app.api import agent, chat, chat_stream, health, knowledge, memory
from app.core.config import settings
from app.core.logging import setup_logger, trace_id_var
from app.memory.reflection_scheduler import reflection_scheduler
from app.core.internal_tokens import internal_tokens
from app.core.telemetry import configure_telemetry


logger = setup_logger("main")


PUBLIC_PATHS = {"/health", "/health/ready", "/metrics", "/docs", "/openapi.json"}
REQUEST_COUNT = Counter(
    "mneme_python_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
REQUEST_DURATION = Histogram(
    "mneme_python_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
CHAT_REQUEST_MAX_BYTES = 64 * 1024


def metric_path(request: Request) -> str:
    """Use the Starlette route template so IDs never become metric labels."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if template:
        return template
    return "unmatched"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.skip_internal_auth and not settings.internal_service_token:
        raise RuntimeError("INTERNAL_SERVICE_TOKEN must be configured")
    reflection_scheduler.start()
    logger.info("Mneme Python Agent 已启动")
    try:
        yield
    finally:
        reflection_scheduler.shutdown()
        logger.info("Mneme Python Agent 已停止")


app = FastAPI(
    title="Mneme Agent",
    version="1.0.0",
    description="三级记忆个人学习助手的内部推理服务",
    lifespan=lifespan,
)
configure_telemetry(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TraceAndLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        token = trace_id_var.set(trace_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info("%s %s (%.0fms)", request.method, request.url.path, duration_ms)
            trace_id_var.reset(token)
        path = metric_path(request)
        REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
        REQUEST_DURATION.labels(request.method, path).observe(
            duration_ms / 1000
        )
        response.headers["X-Trace-Id"] = trace_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class ChatRequestSizeMiddleware:
    """Bound the complete JSON body, including ignored or malformed fields."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in {
            "/api/v1/chat",
            "/api/v1/chat/stream",
        }:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > CHAT_REQUEST_MAX_BYTES:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return

        messages = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            total += len(message.get("body", b""))
            if total > CHAT_REQUEST_MAX_BYTES:
                await self._reject(send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send):
        body = b'{"error":{"code":"REQUEST_TOO_LARGE","message":"Chat request body exceeds 65536 bytes"}}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


_rate_limit_store: dict[str, dict[str, float]] = defaultdict(
    lambda: {"tokens": 60.0, "last": time.monotonic()}
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/health", "/health/ready", "/docs", "/openapi.json"}:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        bucket = _rate_limit_store[client]
        now = time.monotonic()
        bucket["tokens"] = min(60.0, bucket["tokens"] + (now - bucket["last"]))
        bucket["last"] = now
        if bucket["tokens"] < 1:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "请求过于频繁，请稍后再试",
                    }
                },
                headers={"Retry-After": "1"},
            )
        bucket["tokens"] -= 1
        return await call_next(request)


class InternalServiceAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if (
            settings.skip_internal_auth
            or request.method == "OPTIONS"
            or request.url.path in PUBLIC_PATHS
        ):
            return await call_next(request)
        supplied = request.headers.get("X-Internal-Service-Token", "")
        if not internal_tokens.accepts(supplied):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "UNAUTHORIZED_SERVICE",
                        "message": "未经授权的内部调用",
                    }
                },
            )
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ChatRequestSizeMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(InternalServiceAuthMiddleware)
app.add_middleware(TraceAndLoggingMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常 [%s %s]: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {"code": "INTERNAL_ERROR", "message": "服务暂时无法处理该请求"}
        },
    )


app.include_router(chat.router)
app.include_router(chat_stream.router)
app.include_router(knowledge.router)
app.include_router(memory.router)
app.include_router(agent.router)
app.include_router(health.router)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
