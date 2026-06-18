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
from app.memory.session_persistence import session_persistence

logger = setup_logger("short_term_memory")

SUMMARY_PROMPT = """请对以下对话历史进行摘要压缩，保留核心信息和关键知识点：

{history}

请用简洁的语言输出摘要。"""

SUMMARY_COOLDOWN_SECONDS = 300  # 5 分钟
KEEP_RECENT_COUNT = 3


class ShortTermMemoryManager:
    """短期记忆管理器

    触发条件：总 token 超过 WORKING_MEMORY_MAX_TOKENS
    频率保护：两次摘要间隔 >= SUMMARY_COOLDOWN_SECONDS
    压缩策略：只压缩超出阈值部分的早期消息，保留最近 KEEP_RECENT_COUNT 条完整消息
    """

    def __init__(self):
        self._store: dict = {}
        self._last_summary_time: dict = {}

    def _persist(self, session_id: str):
        msgs = self._store.get(session_id)
        if msgs:
            session_persistence.save_messages(session_id, msgs)

    def add_message(self, session_id: str, message: Message) -> List[Message]:
        if session_id not in self._store:
            restored = session_persistence.load_messages(session_id)
            if restored:
                self._store[session_id] = restored
                logger.debug(f"会话 {session_id} 从 Redis 恢复 {len(restored)} 条消息")
            else:
                self._store[session_id] = []
        self._store[session_id].append(message)
        self._persist(session_id)
        return self._store[session_id]

    def get_history(self, session_id: str) -> List[Message]:
        msgs = self._store.get(session_id)
        if msgs:
            return msgs
        restored = session_persistence.load_messages(session_id)
        if restored:
            self._store[session_id] = restored
            logger.info(f"会话 {session_id} 从 Redis 恢复 {len(restored)} 条消息")
            return restored
        return []

    def clear(self, session_id: str):
        self._store.pop(session_id, None)
        self._last_summary_time.pop(session_id, None)
        session_persistence.delete_session(session_id)

    def should_summarize(self, session_id: str) -> bool:
        """判断是否需要摘要压缩。"""
        history = self._store.get(session_id, [])
        if len(history) <= KEEP_RECENT_COUNT:
            return False

        total_tokens = sum(m.token_count for m in history)
        if total_tokens <= settings.WORKING_MEMORY_MAX_TOKENS:
            return False

        last_time = self._last_summary_time.get(session_id)
        if last_time and (datetime.now() - last_time).total_seconds() < SUMMARY_COOLDOWN_SECONDS:
            remaining = SUMMARY_COOLDOWN_SECONDS - (datetime.now() - last_time).total_seconds()
            logger.debug(f"会话 {session_id} 摘要冷却中，剩余 {remaining:.0f}s")
            return False

        return True

    def summarize(self, session_id: str):
        """执行增量摘要压缩。"""
        history = self._store.get(session_id, [])
        if not history or len(history) <= KEEP_RECENT_COUNT:
            return

        total_tokens = sum(m.token_count for m in history)
        if total_tokens <= settings.WORKING_MEMORY_MAX_TOKENS:
            return

        keep_tokens = 0
        cut_index = len(history)
        half_threshold = settings.WORKING_MEMORY_MAX_TOKENS // 2

        for i in range(len(history) - 1, -1, -1):
            keep_tokens += history[i].token_count
            if keep_tokens > half_threshold and (len(history) - i) >= KEEP_RECENT_COUNT:
                cut_index = i
                break

        if cut_index <= 0:
            return

        to_summarize = history[:cut_index]
        to_keep = history[cut_index:]

        logger.info(
            f"会话 {session_id} 摘要压缩: 压缩 {len(to_summarize)} 条早期消息 "
            f"(tokens={sum(m.token_count for m in to_summarize)}), "
            f"保留 {len(to_keep)} 条近期消息 (tokens={sum(m.token_count for m in to_keep)})"
        )

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

        summary_msg = Message(
            role="system",
            content=f"[历史摘要] {response.content}",
            timestamp=datetime.now().isoformat(),
            token_count=len(response.content) // 4
        )

        self._store[session_id] = [summary_msg] + to_keep
        self._last_summary_time[session_id] = datetime.now()
        self._persist(session_id)

        new_total = sum(m.token_count for m in self._store[session_id])
        logger.info(f"会话 {session_id} 摘要完成: 压缩后总 token 数 {new_total}")


short_term_memory = ShortTermMemoryManager()
