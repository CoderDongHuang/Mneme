import json
from app.utils.llm import llm
from langchain_core.messages import HumanMessage, SystemMessage
from app.memory.long_term_memory import long_term_memory
from app.core.logging import setup_logger

logger = setup_logger("reflection")

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
    prefs = long_term_memory.get_preferences(user_id)
    weak_points = long_term_memory.get_weak_points(user_id)
    progress = long_term_memory.get_progress(user_id)

    if not prefs and not weak_points:
        logger.info(f"用户 {user_id} 记忆数据不足，跳过反思")
        return {}

    prompt = REFLECTION_PROMPT.format(
        preferences="\n".join([p.content for p in prefs]),
        weak_points="\n".join([f"{wp.topic}({wp.count}次)" for wp in weak_points]),
        progress=f"{progress.current_chapter}/{progress.current_section}" if progress else "无"
    )

    response = llm.invoke([
        SystemMessage(content="你是一个记忆反思器，只输出JSON。"),
        HumanMessage(content=prompt)
    ])

    try:
        result = json.loads(response.content)
        logger.info(f"用户 {user_id} 反思完成")
        return result
    except json.JSONDecodeError:
        logger.warning("反思结果解析失败")
        return {}
