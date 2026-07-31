import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.agents.nodes import build_llm_prompt
from app.agents.runtime import complete_conversation, prepare_conversation
from app.core.config import settings
from app.core.logging import setup_logger
from app.models.chat import ChatRequest
from app.utils.llm import llm


router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_stream_api")


def _event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _source_payload(chunks: list[dict]) -> list[dict]:
    sources = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        sources.append({
            "document_name": metadata.get("source", "未知文档"),
            "page": metadata.get("page") or None,
            "section": metadata.get("section", ""),
            "chunk_type": metadata.get("chunk_type", "text"),
            "chunk_content": chunk.get("content", ""),
            "score": chunk.get("score", 0.0),
        })
    return sources


def _retrieval_fallback(state: dict) -> str:
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return "当前模型服务暂时不可用，本次也没有检索到可直接作答的资料片段，请稍后重试。"
    excerpts = []
    for index, chunk in enumerate(chunks[:3], start=1):
        content = str(chunk.get("content", "")).strip()
        if content:
            excerpts.append(f"{index}. {content}")
    if not excerpts:
        return "当前模型服务暂时不可用，本次也没有检索到可直接作答的资料片段，请稍后重试。"
    return "在线模型响应超时，以下是从资料库直接检索到的相关原文：\n\n" + "\n\n".join(excerpts)


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    state = prepare_conversation(request)
    prompt = build_llm_prompt(state)

    async def generate():
        answer = ""
        yield _event("meta", {
            "intent": state.get("intent", "general"),
            "sources": _source_payload(state.get("retrieved_chunks", [])),
        })
        try:
            try:
                stream = llm.astream([HumanMessage(content=prompt)]).__aiter__()
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            stream.__anext__(), timeout=settings.stream_timeout_seconds
                        )
                    except StopAsyncIteration:
                        break
                    content = str(chunk.content or "")
                    if content:
                        answer += content
                        yield _event("token", {"content": content})
            except asyncio.TimeoutError:
                logger.warning("流式模型调用超过 %s 秒，启用检索降级", settings.stream_timeout_seconds)
                if not answer:
                    answer = _retrieval_fallback(state)
                    yield _event("token", {"content": answer})
                else:
                    suffix = "\n\n模型连接已超时，回答提前结束。"
                    answer += suffix
                    yield _event("token", {"content": suffix})

            memory_result = complete_conversation(request, state, answer)
            if memory_result.get("pending_memories"):
                yield _event("memory", {"pending": memory_result["pending_memories"]})
            yield _event("done", {"answer_length": len(answer)})
        except Exception as error:
            logger.exception("流式回答失败: %s", error)
            yield _event("error", {"message": str(error)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
