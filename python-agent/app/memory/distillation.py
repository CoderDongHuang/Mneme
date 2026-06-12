import json
import uuid
from datetime import datetime
from app.utils.llm import llm
from app.memory.long_term_memory import long_term_memory
from app.core.logging import setup_logger
from langchain_core.messages import HumanMessage, SystemMessage

logger = setup_logger("distillation")

DISTILLATION_PROMPT = """请从以下对话中提取关键信息，用于更新用户的长期记忆。
提取类型：
- preference：用户的学习偏好（如"喜欢图表"、"不喜欢公式推导"）
- weak_point：用户的知识薄弱点（如"反向传播推导不熟练"）
- progress：用户的学习进度（如"学到第三章第二节"）

对话内容：
{conversation}

输出 JSON 格式：
[
  {{"category": "preference", "content": "...", "confidence": 0.9}},
  {{"category": "weak_point", "content": "...", "topic": "...", "confidence": 0.8}}
]

如果没有可提取的信息，输出空数组 []。"""

def distill_conversation(session_id: str, conversation: list) -> list:
    """蒸馏对话，提取关键信息"""
    if not conversation:
        return []

    conversation_text = "\n".join([f"{m['role']}: {m['content']}" for m in conversation])
    prompt = DISTILLATION_PROMPT.format(conversation=conversation_text)

    response = llm.invoke([
        SystemMessage(content="你是一个记忆蒸馏器，只输出JSON数组。"),
        HumanMessage(content=prompt)
    ])

    try:
        entries = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning("蒸馏输出解析失败")
        return []

    # 过滤低置信度
    filtered = [e for e in entries if e.get("confidence", 0) >= 0.6]
    logger.info(f"蒸馏完成，提取 {len(filtered)} 条记忆")
    return filtered

def apply_distilled_entries(user_id: str, entries: list):
    """应用蒸馏结果到长期记忆"""
    for entry in entries:
        category = entry.get("category")
        content = entry.get("content", "")

        if category == "preference":
            long_term_memory.add_preference(user_id, content)
        elif category == "weak_point":
            topic = entry.get("topic", content)
            long_term_memory.add_weak_point(user_id, content, topic)
        elif category == "progress":
            parts = content.split("/")
            chapter = parts[0] if parts else ""
            section = parts[1] if len(parts) > 1 else ""
            long_term_memory.update_progress(user_id, chapter, section)
