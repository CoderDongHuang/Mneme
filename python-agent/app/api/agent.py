from fastapi import APIRouter

from app.agents.trace_store import agent_trace_store
from app.tools.registry import tool_registry


router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.get("/tools")
async def list_tools() -> dict:
    return {"tools": tool_registry.list_specs()}


@router.get("/traces/{session_id}")
async def list_traces(
    session_id: str, user_id: str = "default", limit: int = 100
) -> dict:
    return {
        "session_id": session_id,
        "traces": agent_trace_store.list_session(user_id, session_id, limit),
    }
