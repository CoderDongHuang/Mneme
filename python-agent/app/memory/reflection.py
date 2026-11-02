import json
from app.core.privacy import require_cloud_processing
from app.utils.llm import llm
from langchain_core.messages import HumanMessage, SystemMessage
from app.memory.long_term_memory import long_term_memory
from app.core.logging import setup_logger, memory_log_fields

logger = setup_logger("reflection")


class ReflectionResultError(ValueError):
    """Invalid provider output must not acknowledge durable reflection work."""


def _parse_result(content: str) -> dict:
    if not isinstance(content, str):
        raise ReflectionResultError("Invalid reflection content type")
    invalid_json = False
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # JSONDecodeError retains the original document. Do not propagate it or
        # put provider output in diagnostics, even through the error message.
        invalid_json = True
    if invalid_json:
        raise ReflectionResultError("Invalid reflection JSON")
    fields = {"implicit_preferences", "priority_weak_points", "next_step_suggestion"}
    if (not isinstance(result, dict) or set(result) != fields
            or not isinstance(result["next_step_suggestion"], str)
            or any(not isinstance(result[field], list)
                   or any(not isinstance(item, str) for item in result[field])
                   for field in ("implicit_preferences", "priority_weak_points"))):
        raise ReflectionResultError("Invalid reflection schema")
    return result

REFLECTION_PROMPT = """请分析以下用户记忆数据，挖掘隐性偏好和学习模式：

偏好列表：{preferences}
薄弱点列表：{weak_points}
学习进度：{progress}

请分析：
1. 用户是否有隐含的学习偏好？（如连续跳过数学推导→不喜欢公式）
2. 哪些薄弱点应该优先处理？
3. 下一步学习建议是什么？

输出 JSON 格式：
{{
  "implicit_preferences": ["..."],
  "priority_weak_points": ["..."],
  "next_step_suggestion": "..."
}}"""


def run_reflection(user_id: str) -> dict:
    """执行记忆反思"""
    require_cloud_processing(user_id)
    prefs = long_term_memory.get_preferences(user_id)
    weak_points = long_term_memory.get_weak_points(user_id)
    progress = long_term_memory.get_progress(user_id)

    if not prefs and not weak_points:
        logger.info(memory_log_fields("reflect", "insufficient_data", user_id=user_id))
        return {}

    prompt = REFLECTION_PROMPT.format(
        preferences="\n".join([p.get("content", "") for p in prefs]),
        weak_points="\n".join(
            [
                f"{wp.get('topic', '')}(重要性{wp.get('importance', 0.5):.1f})"
                for wp in weak_points
            ]
        ),
        progress=progress.get("topic", "无") if progress else "无",
    )

    response = llm.invoke(
        [
            SystemMessage(content="你是一个记忆反思器，只输出JSON。"),
            HumanMessage(content=prompt),
        ]
    )

    result = _parse_result(response.content)
    logger.info(memory_log_fields("reflect", "completed", user_id=user_id))
    return result
