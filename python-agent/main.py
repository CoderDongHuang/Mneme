import signal
import sys
import time
from collections import defaultdict
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import chat, knowledge, health, memory, chat_stream
from app.memory.reflection_scheduler import reflection_scheduler
from app.core.logging import setup_logger

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
logger = setup_logger("main")

app = FastAPI(
    title="Mneme Agent",
    version="0.4.0",
    description="具备三级记忆架构的个人学习助手 Agent API",
)

# ── CORS ──────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Trace ID ──────────────────────────────────────────────
class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id", "")
        trace_id_var.set(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

app.add_middleware(TraceIdMiddleware)


# ── 安全头 ────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# ── 限流中间件 ────────────────────────────────────────────
# 简易令牌桶：每个 IP 每分钟 30 次请求
_rate_limit_store: dict = defaultdict(lambda: {"tokens": 30, "last": time.time()})

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 跳过健康检查
        if request.url.path in ("/health", "/health/ready"):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        bucket = _rate_limit_store[client]
        now = time.time()
        elapsed = now - bucket["last"]
        bucket["tokens"] = min(30, bucket["tokens"] + elapsed * (30 / 60))
        bucket["last"] = now

        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return await call_next(request)

        return JSONResponse(
            status_code=429,
            content={"error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后再试"}},
        )

app.add_middleware(RateLimitMiddleware)


# ── 全局异常处理 ──────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未捕获异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
            }
        },
    )


# ── 路由注册 ──────────────────────────────────────────────
app.include_router(chat.router)
app.include_router(chat_stream.router)
app.include_router(knowledge.router)
app.include_router(health.router)
app.include_router(memory.router)

# ── 调度器 ────────────────────────────────────────────────
reflection_scheduler.start()


# ── 优雅关闭 ──────────────────────────────────────────────
def _shutdown():
    logger.info("收到终止信号，开始优雅关闭...")
    reflection_scheduler.shutdown()

def _signal_handler(signum, frame):
    _shutdown()
    sys.exit(0)

signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

# ── 启动入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
