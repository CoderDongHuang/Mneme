from fastapi import APIRouter, Response

from app.knowledge.vector_store import vector_store
from app.memory.session_persistence import session_persistence
from app.utils.llm import llm


router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mneme-python-agent"}


@router.get("/health/ready")
async def readiness(response: Response) -> dict:
    chroma_ok = False
    try:
        chroma_ok = vector_store.heartbeat()
    except Exception:
        chroma_ok = False
    ready = chroma_ok and llm.configured
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "degraded",
        "components": {
            "chroma": "up" if chroma_ok else "down",
            "llm": llm.status,
            "redis": "up" if session_persistence.available else "optional_down",
        },
    }
