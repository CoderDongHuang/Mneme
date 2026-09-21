import hmac

from fastapi import APIRouter, Header, HTTPException

from app.agents.trace_store import agent_trace_store
from app.tools.registry import tool_registry
from app.core.internal_tokens import internal_tokens
from app.core.config import settings
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class InternalTokenRotation(BaseModel):
    new_token: str = Field(min_length=32, max_length=512)


class ToolApprovalRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    approved_by: str = Field(min_length=1, max_length=128)
    ttl_seconds: int | None = Field(default=None, ge=60, le=86400)


@router.get("/tools")
async def list_tools() -> dict:
    return {"tools": tool_registry.list_specs()}


@router.post("/tools/{tool_name}/approve")
async def approve_tool(
    tool_name: str,
    request: ToolApprovalRequest,
    x_admin_api_token: str = Header(default=""),
) -> dict:
    if not settings.admin_api_token or not hmac.compare_digest(x_admin_api_token, settings.admin_api_token):
        raise HTTPException(status_code=403, detail="需要管理员令牌才能审批工具")
    token = tool_registry.approve(tool_name, request.user_id, request.approved_by, request.ttl_seconds)
    return {"tool": tool_name, "user_id": request.user_id, "approval_token": token}


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
