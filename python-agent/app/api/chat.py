from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.models.chat import ChatRequest, ChatResponse, PendingMemory
from app.agents.nodes import build_llm_prompt
from app.agents.runtime import complete_conversation, prepare_conversation
from app.utils.llm import llm
from app.memory.session_store import session_store
from app.memory.short_term_memory import short_term_memory
from app.memory.working_memory import working_memory
from app.memory.session_persistence import session_persistence
from app.agents.trace_store import agent_trace_store
from langchain_core.messages import HumanMessage
from app.core.logging import setup_logger
from app.knowledge.citations import select_citations, NO_EVIDENCE_ANSWER
from app.knowledge.grounding import verify_evidence_answer
from app.core.telemetry import tracer
from app.core.privacy import privacy_store
from app.knowledge.source_payload import citation_sources

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_api")


@router.get(
    "/sessions",
    summary="历史会话列表",
    description="获取用户的所有历史会话，按时间倒序排列，自动清理 30 天以上无活动的会话",
)
async def list_sessions(user_id: str = "default"):
    sessions = session_store.get_sessions(user_id)
    return {"sessions": sessions}


@router.get(
    "/session/{session_id}",
    summary="会话详情",
    description="获取指定会话的完整消息历史，优先从短期记忆读取，降级到工作记忆",
)
async def get_session(session_id: str):
    messages = short_term_memory.get_history(session_id)
    if not messages:
        messages = working_memory.get_messages(session_id)
    return {
        "session_id": session_id,
        "messages": [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in messages
        ],
    }


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, user_id: str = "default"):
    session_store.delete_session(user_id, session_id)
    short_term_memory.clear(session_id)
    working_memory.clear(session_id)
    return {"deleted": True, "session_id": session_id}


@router.delete("/admin/user/{user_id}")
async def delete_user_sessions(user_id: str):
    session_ids = session_store.cleanup_session_ids(user_id)
    for session_id in session_ids:
        short_term_memory.clear(session_id)
        working_memory.clear(session_id)
    traces = agent_trace_store.delete_user(user_id)
    privacy_store.delete(user_id)
    for offset in range(0, len(session_ids), 1000):
        if session_persistence.count_sessions(session_ids[offset:offset + 1000]) != 0:
            raise RuntimeError("Redis 会话清理后仍有残留")
    # Keep the cleanup manifest until all preceding stages have succeeded.
    session_store.delete_user(user_id)
    return {"status": "deleted", "user_id": user_id, "traces": traces}


class SessionCacheCleanup(BaseModel):
    session_ids: list[str] = Field(min_length=1, max_length=1000)


@router.post("/admin/user/{user_id}/session-cache")
async def delete_canonical_session_caches(user_id: str, request: SessionCacheCleanup):
    """Internal only: Gateway supplies its authoritative, user-scoped MySQL IDs.

    This includes sessions missing from the Agent's optional JSON/TTL cache.
    Batches bound request size without requiring an unbounded account manifest.
    """
    if any(not value.isascii() or not value.isdecimal() or len(value) > 20 for value in request.session_ids):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="会话编号无效")
    for session_id in request.session_ids:
        short_term_memory.clear(session_id)
        working_memory.clear(session_id)
    if session_persistence.count_sessions(request.session_ids) != 0:
        raise RuntimeError("Redis 会话清理后仍有残留")
    return {"status": "verified", "checked_sessions": len(request.session_ids), "redis_sessions": 0}


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="同步对话",
    description="发送消息并等待完整回复后返回 JSON，含答案、参考来源、待确认记忆和记忆洞察",
)
async def chat(request: ChatRequest):
    logger.info("收到对话请求: user_id=%s request_id=%s", request.user_id, request.request_id)

    state = prepare_conversation(request)
    with tracer.start_as_current_span("mneme.llm.invoke") as span:
        span.set_attribute("mneme.llm.streaming", False)
        response = (
            HumanMessage(content=NO_EVIDENCE_ANSWER)
            if state.get("intent") == "qa" and not state.get("retrieved_chunks")
            else llm.invoke([HumanMessage(content=build_llm_prompt(state))])
        )
    answer = await verify_evidence_answer(state, str(response.content or "").strip())
    completion = complete_conversation(request, state, answer)
    result = {**state, **completion, "answer": answer}

    sources = citation_sources(select_citations(result.get("retrieved_chunks", [])))

    # 待确认记忆
    pending_memories = [
        PendingMemory(**pm) for pm in result.get("pending_memories", [])
    ]

    # 从蒸馏产物中提取 memory_insights
    memory_insights = []
    for entry in result.get("memory_entries_to_write", []):
        cat = entry.get("category", "")
        content = entry.get("content", "")
        if cat == "preference":
            memory_insights.append(f"偏好：{content}")
        elif cat == "weak_point":
            memory_insights.append(f"薄弱点：{content}")
        elif cat == "progress":
            memory_insights.append(f"进度：{content}")

    return ChatResponse(
        answer=result.get("answer", ""),
        intent=result.get("intent", "general"),
        sources=sources,
        session_summary=completion.get("session_summary"),
        memory_insights=memory_insights,
        pending_memories=pending_memories,
    )
