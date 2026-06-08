from fastapi import APIRouter
from app.models.chat import ChatRequest, ChatResponse, Source
from app.agents.graph import agent_graph
from app.memory.working_memory import working_memory
from app.memory.short_term_memory import short_term_memory
from app.memory.reflection_scheduler import reflection_scheduler
from app.models.chat import Message
from datetime import datetime
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_api")

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    logger.info(f"收到对话请求: user_id={request.user_id}, message={request.message}")

    # 写入工作记忆和短期记忆
    user_msg = Message(role="user", content=request.message, timestamp=datetime.now().isoformat(), token_count=len(request.message) // 4)
    working_memory.add_message(request.session_id, user_msg)
    short_term_memory.add_message(request.session_id, user_msg)

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

    # 记录会话并检查是否需要触发反思
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

    return ChatResponse(answer=result.get("answer", ""), sources=sources)