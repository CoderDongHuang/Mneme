import json
import re
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts import (
    GENERAL_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
    QA_PROMPT,
    REVIEW_PROMPT,
    SUGGEST_PROMPT,
)
from app.core.config import settings
from app.core.logging import setup_logger
from app.knowledge.retriever import retrieve
from app.knowledge.vector_store import vector_store
from app.memory.distillation import apply_distilled_entries, distill_conversation
from app.memory.long_term_memory import long_term_memory
from app.memory.reflection import run_reflection
from app.memory.short_term_memory import short_term_memory
from app.utils.llm import llm


logger = setup_logger("nodes")
VALID_INTENTS = {"qa", "review", "suggest", "general"}


def _extract_json(content: str) -> dict:
    text = str(content).strip()
    fenced = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(0)
    return json.loads(text)


def _memory_context(user_id: str, session_id: str, include_history: bool = True) -> str:
    preferences = long_term_memory.get_preferences(user_id)
    weak_points = long_term_memory.get_weak_points(user_id)
    progress = long_term_memory.get_progress(user_id)
    sections = []
    if preferences:
        sections.append("偏好：" + "；".join(item.get("content", "") for item in preferences[:8]))
    if weak_points:
        sections.append("薄弱点：" + "；".join(
            item.get("topic") or item.get("content", "") for item in weak_points[:8]
        ))
    if progress:
        sections.append("进度：" + (progress.get("topic") or progress.get("content", "")))
    if include_history:
        history = short_term_memory.get_history(session_id)[-6:]
        if history:
            sections.append("近期对话：\n" + "\n".join(
                f"{message.role}: {message.content}" for message in history
            ))
    return "\n".join(sections) or "暂无明确记录"


def intent_classification_node(state: dict) -> dict:
    message = state.get("message", "").strip()
    if state.get("knowledge_base_ids"):
        return {"intent": "qa", "confidence": 1.0}
    if any(word in message for word in ("建议", "计划", "怎么学", "下一步", "如何复习")):
        return {"intent": "suggest", "confidence": 0.9}
    if any(word in message for word in ("上次", "之前", "回顾", "复习一下", "我的偏好")):
        return {"intent": "review", "confidence": 0.9}
    if message.lower() in {"你好", "您好", "hi", "hello", "谢谢", "再见"}:
        return {"intent": "general", "confidence": 0.95}
    prompt = INTENT_CLASSIFICATION_PROMPT.format(question=state.get("message", ""))
    try:
        response = llm.invoke([
            SystemMessage(content="你是意图分类器，只输出合法 JSON。"),
            HumanMessage(content=prompt),
        ])
        intent_data = _extract_json(response.content)
    except json.JSONDecodeError:
        return {"intent": "general", "confidence": 0.0}
    except Exception as error:
        logger.warning("意图识别调用失败，使用规则降级: %s", error)
        message = state.get("message", "")
        if any(word in message for word in ("建议", "计划", "怎么学", "下一步")):
            return {"intent": "suggest", "confidence": 0.55}
        if any(word in message for word in ("上次", "之前", "回顾", "复习")):
            return {"intent": "review", "confidence": 0.55}
        if state.get("knowledge_base_ids") or len(message) > 8:
            return {"intent": "qa", "confidence": 0.5}
        return {"intent": "general", "confidence": 0.4}

    intent = intent_data.get("intent", "general")
    if intent not in VALID_INTENTS:
        intent = "general"
    if state.get("knowledge_base_ids") and intent == "general":
        intent = "qa"
    confidence = intent_data.get("confidence", 0.5)
    try:
        confidence = max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        confidence = 0.5
    return {"intent": intent, "confidence": confidence}


def knowledge_retrieval_node(state: dict) -> dict:
    kb_ids = list(dict.fromkeys(state.get("knowledge_base_ids") or []))
    if not kb_ids:
        kb_ids = [
            str((collection.metadata or {}).get("kb_id", ""))
            for collection in vector_store.list_user_collections(state["user_id"])
        ]
        kb_ids = [kb_id for kb_id in kb_ids if kb_id]

    chunks = []
    for kb_id in kb_ids:
        chunks.extend(retrieve(state["user_id"], kb_id, state["message"]))
    chunks.sort(key=lambda item: item.get("distance", 1.0))
    chunks = chunks[: settings.retriever_top_k]

    context_parts = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.get("metadata", {})
        location = metadata.get("source", "未知文档")
        if metadata.get("page"):
            location += f"，第 {metadata['page']} 页"
        if metadata.get("section"):
            location += f"，{metadata['section']}"
        context_parts.append(f"[{index}] {location}\n{chunk.get('content', '')}")
    return {
        "context": "\n\n".join(context_parts) or "本次未检索到匹配片段",
        "retrieved_chunks": chunks,
        "knowledge_base_ids": kb_ids,
        "memory_context": _memory_context(state["user_id"], state["session_id"], False),
    }


def memory_retrieval_node(state: dict) -> dict:
    return {"memory_context": _memory_context(state["user_id"], state["session_id"])}


def weak_point_retrieval_node(state: dict) -> dict:
    return {"memory_context": _memory_context(state["user_id"], state["session_id"])}


def suggestion_generation_node(state: dict) -> dict:
    try:
        reflection = run_reflection(state["user_id"])
    except Exception as error:
        logger.warning("实时反思失败，使用已有记忆生成建议: %s", error)
        reflection = {}
    if reflection:
        extra = json.dumps(reflection, ensure_ascii=False)
        current = state.get("memory_context", "")
        return {"memory_context": f"{current}\n反思结果：{extra}"}
    return {}


def build_llm_prompt(state: dict) -> str:
    values = {
        "question": state["message"],
        "context": state.get("context", "本次未检索到匹配片段"),
        "memory_context": state.get("memory_context") or "暂无明确记录",
    }
    intent = state.get("intent", "general")
    template = {
        "qa": QA_PROMPT,
        "review": REVIEW_PROMPT,
        "suggest": SUGGEST_PROMPT,
        "general": GENERAL_PROMPT,
    }.get(intent, GENERAL_PROMPT)
    return template.format(**values)


def llm_reasoning_node(state: dict) -> dict:
    response = llm.invoke([HumanMessage(content=build_llm_prompt(state))])
    if short_term_memory.should_summarize(state["session_id"]):
        short_term_memory.summarize(state["session_id"])
    return {"answer": str(response.content)}


def format_response_node(state: dict) -> dict:
    return {"answer": state.get("answer", "").strip()}


def memory_write_node(state: dict) -> dict:
    user_id = state["user_id"]
    session_id = state["session_id"]
    history = short_term_memory.get_history(session_id)
    if len(history) < 2:
        return {"memory_entries_to_write": []}
    try:
        previous_time = datetime.fromisoformat(history[-2].timestamp)
    except (TypeError, ValueError):
        return {"memory_entries_to_write": []}
    idle_seconds = (datetime.now(previous_time.tzinfo) - previous_time).total_seconds()
    if idle_seconds <= settings.distillation_idle_minutes * 60:
        return {"memory_entries_to_write": []}
    conversation = [
        {"role": message.role, "content": message.content} for message in history[:-1]
    ]
    distilled = distill_conversation(user_id, session_id, conversation)
    pending = apply_distilled_entries(user_id, distilled)
    return {"memory_entries_to_write": distilled, "pending_memories": pending}


def run_pre_llm_nodes(state: dict) -> dict:
    state.update(intent_classification_node(state))
    if state["intent"] == "qa":
        state.update(knowledge_retrieval_node(state))
    elif state["intent"] == "review":
        state.update(memory_retrieval_node(state))
    elif state["intent"] == "suggest":
        state.update(weak_point_retrieval_node(state))
        state.update(suggestion_generation_node(state))
    else:
        state["memory_context"] = _memory_context(
            state["user_id"], state["session_id"], include_history=True
        )
    return state
