from fastapi import APIRouter
from app.models.chat import ChatRequest, ChatResponse, Source, PendingMemory
from app.agents.nodes import build_llm_prompt
from app.agents.runtime import complete_conversation, prepare_conversation
from app.utils.llm import llm
from app.memory.session_store import session_store
from app.memory.short_term_memory import short_term_memory
from app.memory.working_memory import working_memory
from langchain_core.messages import HumanMessage
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_api")

@router.get("/sessions", summary="历史会话列表", description="获取用户的所有历史会话，按时间倒序排列，自动清理 30 天以上无活动的会话")
async def list_sessions(user_id: str = "default"):
    sessions = session_store.get_sessions(user_id)
    return {"sessions": sessions}

@router.get("/session/{session_id}", summary="会话详情", description="获取指定会话的完整消息历史，优先从短期记忆读取，降级到工作记忆")
async def get_session(session_id: str):
    messages = short_term_memory.get_history(session_id)
    if not messages:
        messages = working_memory.get_messages(session_id)
    return {
        "session_id": session_id,
        "messages": [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in messages
        ]
    }


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, user_id: str = "default"):
    session_store.delete_session(user_id, session_id)
    short_term_memory.clear(session_id)
    working_memory.clear(session_id)
    return {"deleted": True, "session_id": session_id}

@router.post("/chat", response_model=ChatResponse, summary="同步对话", description="发送消息并等待完整回复后返回 JSON，含答案、参考来源、待确认记忆和记忆洞察")
async def chat(request: ChatRequest):
    logger.info(f"收到对话请求: user_id={request.user_id}, message={request.message}")

    state = prepare_conversation(request)
    response = llm.invoke([HumanMessage(content=build_llm_prompt(state))])
    answer = str(response.content or "").strip()
    completion = complete_conversation(request, state, answer)
    result = {**state, **completion, "answer": answer}

    sources = []
    for chunk in result.get("retrieved_chunks", []):
        content = chunk.get("content")
        if not content:
            continue
        metadata = chunk.get("metadata", {})
        sources.append(Source(
            document_name=metadata.get("source", "unknown"),
            chunk_content=content,
            page=metadata.get("page"),
            score=chunk.get("score", 0.0)
            ,chunk_type=metadata.get("chunk_type", "text")
        ))

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
