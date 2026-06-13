import json
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from app.utils.llm import llm
from app.agents.prompts import INTENT_CLASSIFICATION_PROMPT, QA_PROMPT
from app.knowledge.retriever import retrieve
from app.knowledge.vector_store import vector_store
from app.memory.short_term_memory import short_term_memory
from app.memory.long_term_memory import long_term_memory
from app.memory.distillation import distill_conversation, apply_distilled_entries
from app.memory.reflection import run_reflection
from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("nodes")

def intent_classification_node(state: dict) -> dict:
    prompt = INTENT_CLASSIFICATION_PROMPT.format(question=state["message"])
    response = llm.invoke([SystemMessage(content="你是一个意图分类器，只输出JSON。"), HumanMessage(content=prompt)])
    try:
        intent_data = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning(f"意图识别JSON解析失败，原始响应: {str(response.content)[:200]}")
        intent_data = {"intent": "general", "confidence": 0.0, "extracted_entities": []}
    logger.info(f"意图识别结果: {intent_data}")
    valid_intents = {"qa", "review", "suggest", "general"}
    intent = intent_data.get("intent", "general")
    if intent not in valid_intents:
        intent = "general"
    return {"intent": intent, "confidence": intent_data.get("confidence", 0.5)}

def knowledge_retrieval_node(state: dict) -> dict:
    all_chunks = []
    kb_ids = state.get("knowledge_base_ids", [])
    
    # 如果没有指定知识库ID，自动检索该用户所有知识库
    if not kb_ids:
        try:
            collections = vector_store.client.list_collections()
            for collection in collections:
                name = collection.name
                if name.startswith(f"user_{state['user_id']}_kb_"):
                    kb_id = name.split("_kb_")[1]
                    chunks = retrieve(state["user_id"], kb_id, state["message"])
                    all_chunks.extend(chunks)
        except Exception as e:
            logger.error(f"自动检索知识库失败: {e}")
    else:
        for kb_id in kb_ids:
            chunks = retrieve(state["user_id"], kb_id, state["message"])
            all_chunks.extend(chunks)
    
    context = "\n\n".join([f"[来源: {c['metadata'].get('source', 'unknown')}] {c['content']}" for c in all_chunks if c.get("content")])
    return {"context": context, "retrieved_chunks": all_chunks}

def memory_retrieval_node(state: dict) -> dict:
    """review 意图：检索记忆"""
    prefs = long_term_memory.get_preferences(state["user_id"])
    weak_points = long_term_memory.get_weak_points(state["user_id"])
    history = short_term_memory.get_history(state["session_id"])

    memory_context = "用户偏好:\n" + "\n".join([p.get("content", "") for p in prefs]) + "\n\n"
    memory_context += "薄弱点:\n" + "\n".join([f"- {wp.get('topic', '')} (重要性{wp.get('importance', 0.5):.1f})" for wp in weak_points]) + "\n\n"
    memory_context += "历史对话:\n" + "\n".join([f"{m.role}: {m.content}" for m in history[-5:]])

    return {"memory_context": memory_context}

def weak_point_retrieval_node(state: dict) -> dict:
    """suggest 意图：检索薄弱点"""
    weak_points = long_term_memory.get_weak_points(state["user_id"])
    progress = long_term_memory.get_progress(state["user_id"])

    context = "薄弱点:\n" + "\n".join([f"- {wp.get('topic', '')}: {wp.get('content', '')}" for wp in weak_points]) + "\n\n"
    if progress:
        topic = progress.get("topic", "")
        context += f"当前进度: {topic}\n\n"

    return {"memory_context": context}

def suggestion_generation_node(state: dict) -> dict:
    """生成学习建议（阶段三：加入反思结果）"""
    weak_points = long_term_memory.get_weak_points(state["user_id"])

    # 尝试获取反思结果
    reflection_result = run_reflection(state["user_id"]) if weak_points else {}
    priority_points = reflection_result.get("priority_weak_points", [])

    context = "薄弱点:\n" + "\n".join([f"- {wp.get('topic', '')}" for wp in weak_points]) + "\n\n"
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

def memory_write_node(state: dict) -> dict:
    """记忆写入（阶段三：蒸馏 + 触发）

    蒸馏触发逻辑：
    - memory_write_node 执行时，当前轮的用户消息已经写入 short_term_memory
    - 因此 history[-1] 是当前消息（时间戳 ≈ 现在），不能用来判断空闲
    - 检查 history[-2]（上一轮的助手回复时间）来判断用户是否空闲超过阈值
    - 至少需要 2 条消息才有"上一轮"的概念
    """
    user_id = state["user_id"]
    session_id = state["session_id"]

    history = short_term_memory.get_history(session_id)
    if len(history) < 2:
        return {"memory_entries_to_write": []}

    # 检查倒数第二条消息的时间（上一轮对话的最后一条消息）
    # 如果距今超过 DISTILLATION_IDLE_MINUTES，说明用户空闲了一段时间
    previous_round_last_msg = history[-2]
    previous_time = datetime.fromisoformat(previous_round_last_msg.timestamp)
    idle_seconds = (datetime.now() - previous_time).total_seconds()

    if idle_seconds > settings.DISTILLATION_IDLE_MINUTES * 60:
        # 蒸馏旧对话：排除当前轮次的用户消息（history[-1]）
        history_dicts = [
            {"role": m.role, "content": m.content}
            for m in history[:-1]
        ]
        distilled = distill_conversation(user_id, session_id, history_dicts)
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
    elif intent == "suggest":
        prompt = f"""你是一个学习助手，基于以下信息回答问题。

{state.get('memory_context', '')}

用户问题：{state['message']}"""
    else:
        # general 意图：直接回答，不需要参考资料
        prompt = f"""你是一个学习助手，请回答用户的问题。

用户问题：{state['message']}

请用简洁清晰的语言回答。"""

    response = llm.invoke([HumanMessage(content=prompt)])

    # 检查是否需要摘要压缩
    if short_term_memory.should_summarize(state["session_id"]):
        short_term_memory.summarize(state["session_id"])

    return {"answer": response.content}