from fastapi import APIRouter
from app.models.chat import ChatRequest, ChatResponse, Source, PendingMemory
from app.agents.graph import agent_graph
from app.memory.working_memory import working_memory
from app.memory.short_term_memory import short_term_memory
from app.memory.session_store import session_store
from app.memory.reflection_scheduler import reflection_scheduler
from app.models.chat import Message
from datetime import datetime
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_api")

@router.get("/sessions")
async def list_sessions(user_id: str = "default"):
    """获取用户的历史对话列表（从 JSON 文件持久化存储读取）"""
    sessions = session_store.get_sessions(user_id)
    return {"sessions": sessions}

@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取单个对话的完整历史（优先从短期记忆，降级到工作记忆）"""
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

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    logger.info(f"收到对话请求: user_id={request.user_id}, message={request.message}")

    # 写入工作记忆和短期记忆
    user_msg = Message(role="user", content=request.message, timestamp=datetime.now().isoformat(), token_count=len(request.message) // 4)
    working_memory.add_message(request.session_id, user_msg)
    short_term_memory.add_message(request.session_id, user_msg)

    # 持久化会话元数据
    session_store.register_session(
        request.user_id, request.session_id,
        title=request.message[:30] + ("..." if len(request.message) > 30 else "")
    )

    result = agent_graph.invoke({
        "user_id": request.user_id,
        "session_id": request.session_id,
        "message": request.message,
        "knowledge_base_ids": request.knowledge_base_ids,
    })

    # 写入助手回复
    if result.get("answer"):
        assistant_msg = Message(role="assistant", content=result["answer"], timestamp=datetime.now().isoformat(), token_count=len(result["answer"]) // 4)
        working_memory.add_message(request.session_id, assistant_msg)
        short_term_memory.add_message(request.session_id, assistant_msg)

    # 更新会话消息计数
    session_store.increment_message_count(request.user_id, request.session_id)

    # 检查摘要压缩 —— 产生 session_summary
    session_summary = None
    if short_term_memory.should_summarize(request.session_id):
        short_term_memory.summarize(request.session_id)
        history = short_term_memory.get_history(request.session_id)
        for m in history:
            if m.role == "system" and m.content.startswith("[历史摘要]"):
                session_summary = m.content
                break

    # 记录会话并异步触发反思
    reflection_scheduler.record_session(request.user_id)
    reflection_scheduler.check_and_trigger(request.user_id)

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
        sources=sources,
        session_summary=session_summary,
        memory_insights=memory_insights,
        pending_memories=pending_memories,
    )