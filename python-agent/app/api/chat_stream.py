import asyncio
import json
import anyio
from contextlib import aclosing
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.agents.nodes import build_llm_prompt
from app.agents.runtime import complete_conversation, prepare_conversation
from app.core.config import settings
from app.core.logging import setup_logger
from app.knowledge.citations import select_citations, NO_EVIDENCE_ANSWER
from app.knowledge.grounding import verify_evidence_answer
from app.models.chat import ChatRequest
from app.knowledge.source_payload import citation_sources
from app.utils.llm import llm
from app.utils.async_stream import closing_async_iterator
from app.core.telemetry import tracer


router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_stream_api")


class ClosingStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await super().__call__(scope, receive, send)
        # ASGI 2.4's default response detects disconnects only on send(). A slow
        # provider may not yield another token, so monitor receive concurrently.
        async with anyio.create_task_group() as group:
            async def consume():
                try:
                    await self.stream_response(send)
                except OSError:
                    pass  # The client socket is already closed.
                finally:
                    group.cancel_scope.cancel()

            group.start_soon(consume)
            await self.listen_for_disconnect(receive)
            group.cancel_scope.cancel()
        if self.background is not None:
            await self.background()

    async def stream_response(self, send):
        # A disconnect may cancel send() while the generator is paused at yield.
        # Close in the consumer task so nested tracer/context scopes exit there.
        async with closing_async_iterator(self.body_iterator):
            await super().stream_response(send)


def _event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _source_payload(chunks: list[dict]) -> list[dict]:
    return [source.model_dump(mode="json") for source in citation_sources(chunks)]


def _retrieval_fallback(state: dict) -> str:
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return (
            "当前模型服务暂时不可用，本次也没有检索到可直接作答的资料片段，请稍后重试。"
        )
    excerpts = []
    for index, chunk in enumerate(chunks[:3], start=1):
        content = str(chunk.get("content", "")).strip()
        if content:
            excerpts.append(f"[{index}] {content}")
    if not excerpts:
        return (
            "当前模型服务暂时不可用，本次也没有检索到可直接作答的资料片段，请稍后重试。"
        )
    return "在线模型响应超时，以下是从资料库直接检索到的相关原文：\n\n" + "\n\n".join(
        excerpts
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request = None) -> StreamingResponse:
    state = prepare_conversation(request)
    prompt = build_llm_prompt(state)

    async def generate():
        answer = ""
        phase = "model_error"
        yield _event(
            "meta",
            {
                "intent": state.get("intent", "general"),
                "sources": _source_payload(
                    select_citations(state.get("retrieved_chunks", []))
                ),
            },
        )
        evidence_mode = state.get("intent") == "qa"
        try:
            try:
                if evidence_mode and not state.get("retrieved_chunks"):
                    answer = NO_EVIDENCE_ANSWER
                else:
                    async with aclosing(model_events()) as events:
                        async for event in events:
                            if evidence_mode:
                                answer += event
                            else:
                                answer += event
                                yield _event("token", {"content": event})
            except asyncio.TimeoutError:
                if http_request is not None:
                    http_request.scope["mneme.stream.reason"] = "model_timeout"
                logger.warning("流式模型调用超时，使用资料原文降级")
                if evidence_mode or not answer:
                    answer = _retrieval_fallback(state)
                    if not evidence_mode:
                        yield _event("token", {"content": answer})
                else:
                    suffix = "\n\n模型连接已超时，回答提前结束。"
                    answer += suffix
                    yield _event("token", {"content": suffix})

            if evidence_mode:
                phase = "grounding_failed"
                answer = await verify_evidence_answer(state, answer)
                yield _event("token", {"content": answer})

            phase = "memory_failed"
            memory_result = complete_conversation(request, state, answer)
            if memory_result.get("pending_memories"):
                yield _event("memory", {"pending": memory_result["pending_memories"]})
            yield _event("done", {"answer_length": len(answer)})
        except Exception as error:
            if http_request is not None:
                http_request.scope["mneme.stream.reason"] = phase
            logger.error("流式回答失败: %s", type(error).__name__)
            yield _event("error", {"message": "模型服务暂时不可用，请稍后重试或检查服务配置。", "code": phase.upper()})

    async def model_events():
        with tracer.start_as_current_span("mneme.llm.stream") as span:
            span.set_attribute("mneme.llm.streaming", True)
            async with closing_async_iterator(llm.astream([HumanMessage(content=prompt)])) as stream:
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            stream.__anext__(), timeout=settings.stream_timeout_seconds
                        )
                    except StopAsyncIteration:
                        break
                    content = str(chunk.content or "")
                    if content:
                        yield content

    return ClosingStreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
