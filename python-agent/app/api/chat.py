from fastapi import APIRouter
from app.models.chat import ChatRequest, ChatResponse, Source
from app.agents.graph import agent_graph
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_api")

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    logger.info(f"收到对话请求: user_id={request.user_id}, message={request.message}")
    result = agent_graph.invoke({
        "user_id": request.user_id,
        "session_id": request.session_id,
        "message": request.message,
        "knowledge_base_ids": request.knowledge_base_ids,
    })

    sources = []
    for chunk in result.get("retrieved_chunks", []):
        metadata = chunk.get("metadata", {})
        sources.append(Source(
            document_name=metadata.get("source", "unknown"),
            chunk_content=chunk.get("content", ""),
            page=metadata.get("page"),
            score=chunk.get("score", 0.0)
        ))

    return ChatResponse(answer=result.get("answer", ""), sources=sources)