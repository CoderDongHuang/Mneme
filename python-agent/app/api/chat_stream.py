from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.models.chat import ChatRequest
from app.agents.graph import agent_graph
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_stream_api")

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def generate():
        result = agent_graph.invoke({
            "user_id": request.user_id,
            "session_id": request.session_id,
            "message": request.message,
            "knowledge_base_ids": request.knowledge_base_ids,
        })
        answer = result.get("answer", "")
        # 逐字输出
        for char in answer:
            yield f"data: {char}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
