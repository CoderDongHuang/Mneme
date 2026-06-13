"""
记忆蒸馏模块

职责：
- 从一段对话中提取关键信息（偏好、薄弱点、进度）
- 将提取的信息写入长期记忆
- 写入前进行语义去重（双层：LLM 判断 + 向量相似度）
"""
import json
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from app.utils.llm import llm
from app.memory.long_term_memory import long_term_memory
from app.core.logging import setup_logger

logger = setup_logger("distillation")

DISTILLATION_PROMPT = """请从以下对话中提取关键信息，用于更新用户的长期记忆。

提取类型：
- preference：用户的学习偏好（如"喜欢图表"、"不喜欢公式推导"）
- weak_point：用户的知识薄弱点（如"反向传播推导不熟练"）
- progress：用户的学习进度（如"学到第三章第二节"）

对话内容：
{conversation}

用户已有记忆：
{existing_memories}

要求：
1. 只提取**新出现**的信息，如果某项与已有记忆语义高度重复，跳过不输出
2. 每条提取的 confidence 要合理评估（0.0-1.0），不确定的信息降低 confidence
3. 为 weak_point 指定一个简短的 topic（用于后续去重合并）

输出 JSON 格式：
[
  {{"category": "preference", "content": "...", "confidence": 0.9, "is_new": true}},
  {{"category": "weak_point", "content": "...", "topic": "...", "confidence": 0.8, "is_new": true}}
]

如果没有新的可提取信息，输出空数组 []。"""


def distill_conversation(user_id: str, session_id: str, conversation: list) -> list:
    """蒸馏对话，提取关键信息。

    Args:
        user_id: 用户 ID（用于查询已有记忆做去重）
        session_id: 会话 ID
        conversation: 对话列表 [{"role": "user", "content": "..."}, ...]

    Returns:
        提取的记忆条目列表（已过滤低置信度）
    """
    if not conversation:
        return []

    # 获取已有记忆作为去重参考
    existing = long_term_memory.get_all_memories(user_id)
    existing_text_parts = []
    for pref in existing.get("preferences", []):
        existing_text_parts.append(f"- [偏好] {pref.get('content', '')}")
    for wp in existing.get("weak_points", []):
        existing_text_parts.append(f"- [薄弱点({wp.get('topic', '')})] {wp.get('content', '')}")
    if existing.get("progress"):
        p = existing["progress"]
        existing_text_parts.append(f"- [进度] {p.get('topic', '')}: {p.get('content', '')}")

    existing_text = "\n".join(existing_text_parts) if existing_text_parts else "（暂无已有记忆）"

    conversation_text = "\n".join([f"{m['role']}: {m['content']}" for m in conversation])
    prompt = DISTILLATION_PROMPT.format(
        conversation=conversation_text,
        existing_memories=existing_text
    )

    response = llm.invoke([
        SystemMessage(content="你是一个记忆蒸馏器，只输出JSON数组。"),
        HumanMessage(content=prompt)
    ])

    try:
        entries = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning(f"蒸馏输出 JSON 解析失败，原始响应前200字符: {str(response.content)[:200]}")
        return []

    # 过滤低置信度和标记为不新的条目
    filtered = [
        e for e in entries
        if e.get("confidence", 0) >= 0.6 and e.get("is_new", True)
    ]
    logger.info(
        f"蒸馏完成: 原始提取 {len(entries)} 条, "
        f"过滤后 {len(filtered)} 条 "
        f"(阈值={0.6}, session={session_id})"
    )
    return filtered


def apply_distilled_entries(user_id: str, entries: list):
    """应用蒸馏结果到长期记忆。

    长记忆层（LongTermMemoryManager）内部已做向量级语义去重，
    此处只做分类路由。
    """
    written = 0
    skipped = 0
    for entry in entries:
        category = entry.get("category")
        content = entry.get("content", "")

        if category == "preference":
            result = long_term_memory.add_preference(user_id, content)
            if result:
                written += 1
            else:
                skipped += 1  # 语义去重命中
        elif category == "weak_point":
            topic = entry.get("topic", content)
            result = long_term_memory.add_weak_point(user_id, content, topic)
            if result:
                written += 1
            else:
                skipped += 1
        elif category == "progress":
            parts = content.split("/")
            chapter = parts[0] if parts else ""
            section = parts[1] if len(parts) > 1 else ""
            long_term_memory.update_progress(user_id, chapter, section)
            written += 1

    if written or skipped:
        logger.info(f"蒸馏入库: 写入 {written} 条, 去重跳过 {skipped} 条")
