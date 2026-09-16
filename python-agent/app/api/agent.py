from fastapi import APIRouter

from app.agents.trace_store import agent_trace_store
from app.tools.registry import tool_registry
from app.core.internal_tokens import internal_tokens
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class InternalTokenRotation(BaseModel):
    new_token: str = Field(min_length=32, max_length=512)


@router.get("/tools")
async def list_tools() -> dict:
    return {"tools": tool_registry.list_specs()}


@router.post("/secrets/internal-token/rotate")
async def rotate_internal_token(request: InternalTokenRotation) -> dict:
    return {"status": "rotated", **internal_tokens.rotate(request.new_token)}


@router.get("/traces/{session_id}")
async def list_traces(
    session_id: str, user_id: str = "default", limit: int = 100
) -> dict:
    return {
        "session_id": session_id,
        "traces": agent_trace_store.list_session(user_id, session_id, limit),
    }
