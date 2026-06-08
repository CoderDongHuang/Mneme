import json
from langchain_core.messages import HumanMessage, SystemMessage
from app.utils.llm import llm
from app.agents.prompts import INTENT_CLASSIFICATION_PROMPT, QA_PROMPT
from app.knowledge.retriever import retrieve
from app.memory.working_memory import working_memory
from app.memory.short_term_memory import short_term_memory
from app.memory.long_term_memory import long_term_memory
from app.models.chat import Message
from datetime import datetime
from app.core.logging import setup_logger

logger = setup_logger("nodes")

def intent_classification_node(state: dict) -> dict:
    prompt = INTENT_CLASSIFICATION_PROMPT.format(question=state["message"])
    response = llm.invoke([SystemMessage(content="你是一个意图分类器，只输出JSON。"), HumanMessage(content=prompt)])
    try:
        intent_data = json.loads(response.content)
    except:
        intent_data = {"intent": "qa", "confidence": 0.5, "extracted_entities": []}
    logger.info(f"意图识别结果: {intent_data}")
    valid_intents = {"qa", "review", "suggest"}
    intent = intent_data.get("intent", "qa")
    if intent not in valid_intents:
        intent = "qa"
    return {"intent": intent, "confidence": intent_data.get("confidence", 0.5)}

def knowledge_retrieval_node(state: dict) -> dict:
    all_chunks = []
    for kb_id in state.get("knowledge_base_ids", []):
        chunks = retrieve(state["user_id"], kb_id, state["message"])
        all_chunks.extend(chunks)
    context = "\n\n".join([f"[来源: {c['metadata'].get('source', 'unknown')}] {c['content']}" for c in all_chunks if c.get("content")])
    return {"context": context, "retrieved_chunks": all_chunks}

def memory_retrieval_node(state: dict) -> dict:
    """review 意图：检索记忆"""
    prefs = long_term_memory.get_preferences(state["user_id"])
    weak_points = long_term_memory.get_weak_points(state["user_id"])
    history = short_term_memory.get_history(state["session_id"])

    memory_context = "用户偏好:\n" + "\n".join([p.content for p in prefs]) + "\n\n"
    memory_context += "薄弱点:\n" + "\n".join([f"- {wp.topic} (提及{wp.count}次)" for wp in weak_points]) + "\n\n"
    memory_context += "历史对话:\n" + "\n".join([f"{m.role}: {m.content}" for m in history[-5:]])

    return {"memory_context": memory_context}

def weak_point_retrieval_node(state: dict) -> dict:
    """suggest 意图：检索薄弱点"""
    weak_points = long_term_memory.get_weak_points(state["user_id"])
    progress = long_term_memory.get_progress(state["user_id"])

    context = "薄弱点:\n" + "\n".join([f"- {wp.topic}: {wp.content}" for wp in weak_points]) + "\n\n"
    if progress:
        context += f"当前进度: {progress.current_chapter}/{progress.current_section}\n\n"

    return {"memory_context": context}

def suggestion_generation_node(state: dict) -> dict:
    """生成学习建议（阶段三：加入反思结果）"""
    weak_points = long_term_memory.get_weak_points(state["user_id"])

    # 尝试获取反思结果
    from app.memory.reflection import run_reflection
    reflection_result = run_reflection(state["user_id"]) if weak_points else {}
    priority_points = reflection_result.get("priority_weak_points", [])

    context = "薄弱点:\n" + "\n".join([f"- {wp.topic}" for wp in weak_points]) + "\n\n"
    if priority_points:
        context += f"优先处理: {', '.join(priority_points)}\n\n"

    prompt = f"""基于以下用户信息，生成 3 条个性化学习建议：

{context}

用户问题：{state['message']}

请用简洁的列表格式输出建议。"""
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"suggestions": [response.content]}

def format_response_node(state: dict) -> dict:
    """格式化响应"""
    intent = state["intent"]
    if intent == "suggest":
        answer = state.get("suggestions", [""])[0]
    else:
        answer = state.get("answer", "")
    return {"answer": answer}

from app.memory.distillation import distill_conversation, apply_distilled_entries
from app.memory.short_term_memory import short_term_memory
from app.core.config import settings
from datetime import datetime

def memory_write_node(state: dict) -> dict:
    """记忆写入（阶段三：蒸馏 + 触发）"""
    user_id = state["user_id"]
    session_id = state["session_id"]

    # 获取完整会话历史
    history = short_term_memory.get_history(session_id)
    history_dicts = [{"role": m.role, "content": m.content} for m in history]

    # 蒸馏触发：检查上次消息时间，超过 15 分钟则蒸馏
    if history:
        last_msg = history[-1]
        last_time = datetime.fromisoformat(last_msg.timestamp)
        if (datetime.now() - last_time).total_seconds() > settings.DISTILLATION_IDLE_MINUTES * 60:
            distilled = distill_conversation(session_id, history_dicts[:-1])  # 蒸馏旧对话
            apply_distilled_entries(user_id, distilled)

    return {"memory_entries_to_write": []}

def llm_reasoning_node(state: dict) -> dict:
    intent = state["intent"]

    if intent == "qa":
        prompt = QA_PROMPT.format(
            context=state.get("context", "无参考资料"),
            question=state["message"]
        )
    elif intent == "review":
        prompt = f"""你是一个学习助手，基于用户的历史记忆回答问题。

{state.get('memory_context', '')}

用户问题：{state['message']}

请结合历史记忆和偏好回答。"""
    else:
        prompt = f"""你是一个学习助手，基于以下信息回答问题。

{state.get('memory_context', '')}

用户问题：{state['message']}"""

    response = llm.invoke([HumanMessage(content=prompt)])

    # 检查是否需要摘要压缩
    if short_term_memory.should_summarize(state["session_id"]):
        short_term_memory.summarize(state["session_id"])

    return {"answer": response.content}