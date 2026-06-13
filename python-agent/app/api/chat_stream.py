"""
流式对话接口 — 真正的 token 级别流式输出

与 /api/v1/chat 的区别：
- /chat: 等待完整结果后一次性返回 JSON
- /chat/stream: 先跑意图识别 + 检索（秒级），再对 LLM 推理逐 token 推送（SSE）

设计：
1. 非流式阶段（~1-2s）：意图识别 → 知识库/记忆检索 → 构建 prompt
2. 流式阶段（逐 token）：LLM 推理，每个 token 立即推送到客户端
3. 收尾阶段：写入记忆、调度反思
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from app.models.chat import ChatRequest, Message
from app.agents.nodes import (
    intent_classification_node,
    knowledge_retrieval_node,
    memory_retrieval_node,
    weak_point_retrieval_node,
    memory_write_node,
)
from app.agents.prompts import QA_PROMPT
from app.memory.working_memory import working_memory
from app.memory.short_term_memory import short_term_memory
from app.memory.reflection_scheduler import reflection_scheduler
from app.utils.llm import llm
from app.core.logging import setup_logger
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = setup_logger("chat_stream_api")


def _build_llm_prompt(state: dict) -> str:
    """根据意图构建 LLM 推理 prompt（与 nodes.py llm_reasoning_node 保持一致）"""
    intent = state["intent"]

    if intent == "qa":
        return QA_PROMPT.format(
            context=state.get("context", "无参考资料"),
            question=state["message"]
        )
    elif intent == "review":
        return f"""你是一个学习助手，基于用户的历史记忆回答问题。

{state.get('memory_context', '')}

用户问题：{state['message']}

请结合历史记忆和偏好回答。"""
    elif intent == "suggest":
        # 将反思分析 + 建议生成合并到一个 prompt，一次流式 LLM 调用完成
        return f"""你是一个学习助手。请分析用户的薄弱点并生成个性化学习建议。

用户学习数据：
{state.get('memory_context', '无数据')}

用户问题：{state['message']}

请按以下结构输出：
1. 薄弱点分析：哪些知识点需要优先加强
2. 学习建议（3 条）：具体可执行的下一步学习计划"""
    else:  # general
        return f"""你是一个学习助手，请回答用户的问题。

用户问题：{state['message']}

请用简洁清晰的语言回答。"""


def _run_pre_llm_nodes(state: dict) -> dict:
    """执行 LLM 推理之前的所有节点：意图识别 → 检索（不包含 LLM 调用）

    suggest 意图的特殊处理：
    - suggestion_generation_node 内部有 LLM 调用（反思+建议），不放在非流式阶段
    - 改为只取薄弱点数据，后续在流式阶段一次性生成建议
    """
    # 1. 意图识别
    state.update(intent_classification_node(state))
    intent = state["intent"]
    logger.info(f"流式端点意图识别: intent={intent}, confidence={state.get('confidence', 0)}")

    # 2. 按意图走检索（仅做数据检索，不做 LLM 调用）
    if intent == "qa":
        state.update(knowledge_retrieval_node(state))
    elif intent == "review":
        state.update(memory_retrieval_node(state))
    elif intent == "suggest":
        state.update(weak_point_retrieval_node(state))
    # general 意图不需要检索

    return state


def _run_post_llm_nodes(state: dict, answer: str):
    """LLM 推理完成后：写入记忆、调度反思"""
    state["answer"] = answer

    # 写入助手消息到工作记忆和短期记忆
    assistant_msg = Message(
        role="assistant", content=answer,
        timestamp=datetime.now().isoformat(), token_count=len(answer) // 4
    )
    working_memory.add_message(state["session_id"], assistant_msg)
    short_term_memory.add_message(state["session_id"], assistant_msg)

    # 摘要压缩检查
    if short_term_memory.should_summarize(state["session_id"]):
        short_term_memory.summarize(state["session_id"])

    # 蒸馏 + 反思
    state.update(memory_write_node(state))
    reflection_scheduler.record_session(state["user_id"])
    reflection_scheduler.check_and_trigger(state["user_id"])


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

    # 初始化状态
    state = {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "message": request.message,
        "knowledge_base_ids": request.knowledge_base_ids or [],
    }

    # 执行非流式阶段（意图识别 + 检索）
    state = _run_pre_llm_nodes(state)

    # 构建 prompt
    prompt = _build_llm_prompt(state)

    async def generate():
        full_answer = ""

        try:
            # ── 流式阶段：逐 token 推送 LLM 推理结果 ──
            async for chunk in llm.astream([HumanMessage(content=prompt)]):
                if chunk.content:
                    full_answer += chunk.content
                    yield f"data: {chunk.content}\n\n"

            # ── 收尾阶段 ──
            _run_post_llm_nodes(state, full_answer)

        except Exception as e:
            logger.error(f"流式输出异常: {e}", exc_info=True)
            yield f"data: [ERROR] {str(e)}\n\n"

        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        }
    )
