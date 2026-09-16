from datetime import datetime, timezone

from fastapi import APIRouter, Response

from app.knowledge.vector_store import vector_store
from app.memory.session_persistence import session_persistence
from app.utils.llm import llm
from app.core.config import settings


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


@router.get("/health/config")
async def config_status() -> dict:
    """Expose configuration presence only; never return keys or secret values."""
    return {
        "service": "mneme-python-agent",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "rotation_required": settings.secret_rotation_due,
        "configuration": {
            "llm_api_key": bool(settings.deepseek_api_key or settings.dashscope_api_key),
            "embedding_api_key": bool(settings.dashscope_api_key),
            "redis_configured": bool(settings.redis_host),
            "ocr_enabled": settings.ocr_enabled,
            "multimodal_enabled": settings.multimodal_enabled,
            "offline_embeddings": settings.offline_embeddings,
            "agent_trace_store": bool(settings.agent_trace_store_path),
            "memory_version_store": bool(settings.memory_version_store_path),
            "agent_trace_retention_days": settings.agent_trace_retention_days,
            "memory_version_retention_days": settings.memory_version_retention_days,
            "vector_shard_count": settings.vector_shard_count,
            "vector_shard_id": settings.vector_shard_id,
            "vector_shard_clients": len(vector_store.clients),
            "agent_tool_timeout_seconds": settings.agent_tool_timeout_seconds,
            "agent_trace_redaction": bool(settings.agent_trace_redact_fields),
        },
    }
