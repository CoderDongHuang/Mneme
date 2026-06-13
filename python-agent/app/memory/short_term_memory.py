"""
短期记忆管理器

职责：
- 存储每个会话的完整对话历史
- 当历史 token 总量超过阈值时，对早期消息进行摘要压缩
- 频率保护：两次摘要间隔不少于冷却期，避免反复触发
- 增量压缩：只压缩早期消息，保留最近的完整上下文
"""
from typing import List
from datetime import datetime
from langchain_core.messages import HumanMessage, SystemMessage
from app.models.chat import Message
from app.utils.llm import llm
from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("short_term_memory")

SUMMARY_PROMPT = """请对以下对话历史进行摘要压缩，保留核心信息和关键知识点：

{history}

请用简洁的语言输出摘要。"""

# 两次摘要之间的最小间隔（秒）
SUMMARY_COOLDOWN_SECONDS = 300  # 5 分钟

# 摘要后保留的最近消息条数
KEEP_RECENT_COUNT = 3


class ShortTermMemoryManager:
    """短期记忆管理器

    触发条件：总 token 超过 WORKING_MEMORY_MAX_TOKENS
    频率保护：两次摘要间隔 >= SUMMARY_COOLDOWN_SECONDS
    压缩策略：只压缩超出阈值部分的早期消息，保留最近 KEEP_RECENT_COUNT 条完整消息
    """

    def __init__(self):
        self._store: dict = {}              # session_id → List[Message]
        self._last_summary_time: dict = {}  # session_id → datetime

    def add_message(self, session_id: str, message: Message) -> List[Message]:
        if session_id not in self._store:
            self._store[session_id] = []
        self._store[session_id].append(message)
        return self._store[session_id]

    def get_history(self, session_id: str) -> List[Message]:
        return self._store.get(session_id, [])

    def clear(self, session_id: str):
        self._store.pop(session_id, None)
        self._last_summary_time.pop(session_id, None)

    def should_summarize(self, session_id: str) -> bool:
        """判断是否需要摘要压缩。

        条件：
        1. 历史 token 总量超过阈值
        2. 距上次摘要超过冷却期
        3. 有足够多的消息值得压缩
        """
        history = self._store.get(session_id, [])
        if len(history) <= KEEP_RECENT_COUNT:
            return False

        total_tokens = sum(m.token_count for m in history)
        if total_tokens <= settings.WORKING_MEMORY_MAX_TOKENS:
            return False

        # 冷却期检查
        last_time = self._last_summary_time.get(session_id)
        if last_time and (datetime.now() - last_time).total_seconds() < SUMMARY_COOLDOWN_SECONDS:
            remaining = SUMMARY_COOLDOWN_SECONDS - (datetime.now() - last_time).total_seconds()
            logger.debug(f"会话 {session_id} 摘要冷却中，剩余 {remaining:.0f}s")
            return False

        return True

    def summarize(self, session_id: str):
        """执行增量摘要压缩。

        只压缩早期消息（超出阈值的部分），保留最近 KEEP_RECENT_COUNT 条完整消息。
        """
        history = self._store.get(session_id, [])
        if not history or len(history) <= KEEP_RECENT_COUNT:
            return

        total_tokens = sum(m.token_count for m in history)
        if total_tokens <= settings.WORKING_MEMORY_MAX_TOKENS:
            return

        # 增量压缩：从旧到新计算，找到需要压缩的消息范围
        # 保留最近 KEEP_RECENT_COUNT 条 + 差不多一半 token 阈值的近期消息
        keep_tokens = 0
        cut_index = len(history)
        half_threshold = settings.WORKING_MEMORY_MAX_TOKENS // 2

        for i in range(len(history) - 1, -1, -1):
            keep_tokens += history[i].token_count
            if keep_tokens > half_threshold and (len(history) - i) >= KEEP_RECENT_COUNT:
                cut_index = i
                break

        if cut_index <= 0:
            # 所有消息都需要保留
            return

        to_summarize = history[:cut_index]   # 需要压缩的早期消息
        to_keep = history[cut_index:]         # 保留的近期消息

        logger.info(
            f"会话 {session_id} 摘要压缩: 压缩 {len(to_summarize)} 条早期消息 "
            f"(tokens={sum(m.token_count for m in to_summarize)}), "
            f"保留 {len(to_keep)} 条近期消息 (tokens={sum(m.token_count for m in to_keep)})"
        )

        # 构建摘要 prompt
        history_text = "\n".join([f"{m.role}: {m.content}" for m in to_summarize])
        prompt = SUMMARY_PROMPT.format(history=history_text)

        try:
            response = llm.invoke([
                SystemMessage(content="你是一个对话摘要压缩器，只输出摘要内容。"),
                HumanMessage(content=prompt)
            ])
        except Exception as e:
            logger.error(f"摘要压缩 LLM 调用失败: {e}")
            return

        # 创建摘要消息（放在最前面）
        summary_msg = Message(
            role="system",
            content=f"[历史摘要] {response.content}",
            timestamp=datetime.now().isoformat(),
            token_count=len(response.content) // 4
        )

        # 更新存储：摘要 + 近期消息
        self._store[session_id] = [summary_msg] + to_keep
        self._last_summary_time[session_id] = datetime.now()

        new_total = sum(m.token_count for m in self._store[session_id])
        logger.info(f"会话 {session_id} 摘要完成: 压缩后总 token 数 {new_total}")


# 全局单例
short_term_memory = ShortTermMemoryManager()
