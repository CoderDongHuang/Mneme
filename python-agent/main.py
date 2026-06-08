from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from contextvars import ContextVar
from app.api import chat, knowledge, health, memory, chat_stream
from app.memory.reflection_scheduler import reflection_scheduler

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

app = FastAPI(title="Mneme Agent", version="0.3.0")

class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id", "")
        trace_id_var.set(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

app.add_middleware(TraceIdMiddleware)

app.include_router(chat.router)
app.include_router(chat_stream.router)
app.include_router(knowledge.router)
app.include_router(health.router)
app.include_router(memory.router)

reflection_scheduler.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)