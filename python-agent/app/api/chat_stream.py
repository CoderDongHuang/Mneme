"""
流式对话接口 — 真正的 token 级别流式输出

与 /api/v1/chat 的区别：
- /chat: 等待完整结果后一次性返回 JSON
- /chat/stream: 先跑意图识别 + 检索（秒级），再对 LLM 推理逐 token 推送（SSE）

设计：
1. 非流式阶段（~1-2s）：意图识别 → 知识库/记忆检索 → 构建 prompt
2. 流式阶段（逐 token）：LLM 推理，每个 token 立即推送到客户端
3. 收尾阶段：写入记忆、调度反思

prompt 构建和检索节点复用 nodes.py 中的公共函数，
避免与 graph 路径的逻辑重复。
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.models.chat import ChatRequest, Message, PendingMemory
from app.agents.nodes import (
    build_llm_prompt,
    run_pre_llm_nodes,
    memory_write_node,
)
from app.memory.working_memory import working_memory
from app.memory.short_term_memory import short_term_memory
from app.memory.session_store import session_store
from app.memory.reflection_scheduler import reflection_scheduler
from app.utils.llm import llm
from app.core.logging import setup_logger
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_stream_api")


def _run_post_llm_nodes(state: dict, answer: str) -> dict:
    """LLM 推理完成后：写入记忆、调度反思。

    Returns:
        {"pending": [...], "memory_insights": [...], "session_summary": str}
    """
    state["answer"] = answer

    # 写入助手消息到工作记忆和短期记忆
    assistant_msg = Message(
        role="assistant", content=answer,
        timestamp=datetime.now().isoformat(), token_count=len(answer) // 4
    )
    working_memory.add_message(state["session_id"], assistant_msg)
    short_term_memory.add_message(state["session_id"], assistant_msg)

    # 更新会话消息计数
    session_store.increment_message_count(state["user_id"], state["session_id"])

    # 摘要压缩检查 —— 产生 session_summary
    session_summary = None
    if short_term_memory.should_summarize(state["session_id"]):
        short_term_memory.summarize(state["session_id"])
        # 取摘要消息的内容作为 session_summary
        history = short_term_memory.get_history(state["session_id"])
        for m in history:
            if m.role == "system" and m.content.startswith("[历史摘要]"):
                session_summary = m.content
                break

    # 蒸馏 —— 产生 pending_memories 和 memory_insights
    state.update(memory_write_node(state))
    reflection_scheduler.record_session(state["user_id"])
    reflection_scheduler.check_and_trigger(state["user_id"])

    pending = state.get("pending_memories", [])
    memory_entries = state.get("memory_entries_to_write", [])

    # 从蒸馏产物中提取洞察
    memory_insights = []
    for entry in memory_entries:
        cat = entry.get("category", "")
        content = entry.get("content", "")
        if cat == "preference":
            memory_insights.append(f"偏好：{content}")
        elif cat == "weak_point":
            memory_insights.append(f"薄弱点：{content}")
        elif cat == "progress":
            memory_insights.append(f"进度：{content}")

    return {
        "pending": pending,
        "memory_insights": memory_insights,
        "session_summary": session_summary,
    }


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式对话接口：SSE 协议，逐 token 推送 LLM 推理结果"""

    # 写入用户消息到记忆
    user_msg = Message(
        role="user", content=request.message,
        timestamp=datetime.now().isoformat(), token_count=len(request.message) // 4
    )
    working_memory.add_message(request.session_id, user_msg)
    short_term_memory.add_message(request.session_id, user_msg)

    # 持久化会话元数据
    session_store.register_session(
        request.user_id, request.session_id,
        title=request.message[:30] + ("..." if len(request.message) > 30 else "")
    )

    # 初始化状态
    state = {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "message": request.message,
        "knowledge_base_ids": request.knowledge_base_ids or [],
    }

    # 执行非流式阶段（复用 nodes.py 的公共函数）
    state = run_pre_llm_nodes(state)

    # 构建 prompt（复用 nodes.py 的公共函数）
    prompt = build_llm_prompt(state)

    async def generate():
        full_answer = ""
        pending = []

        try:
            # ── 流式阶段：逐 token 推送 LLM 推理结果 ──
            async for chunk in llm.astream([HumanMessage(content=prompt)]):
                if chunk.content:
                    full_answer += chunk.content
                    yield f"data: {chunk.content}\n\n"

            # ── 收尾阶段 ──
            post_result = _run_post_llm_nodes(state, full_answer)
            pending = post_result.get("pending", [])

        except Exception as e:
            logger.error(f"流式输出异常: {e}", exc_info=True)
            yield f"data: [ERROR] {str(e)}\n\n"

        finally:
            if pending:
                import json as _json
                yield f"data: [PENDING] {_json.dumps(pending, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
