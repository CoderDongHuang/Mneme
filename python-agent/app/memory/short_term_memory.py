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
from threading import RLock
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.time import parse_utc, utc_now
from app.models.chat import Message
from app.utils.llm import llm
from app.core.config import settings
from app.core.logging import setup_logger, memory_log_fields
from app.memory.session_persistence import session_persistence
from app.memory.session_scope import account_session, cache_key, session_revision
from app.memory import session_history

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
        self._revisions: dict = {}
        self._lock = RLock()

    @staticmethod
    def _copy(messages):
        return [message.model_copy(deep=True) for message in messages]

    def _history(self, session_id, user_id, state):
        key = cache_key(user_id, session_id)
        # Always validate SQL history, including inactivity expiry. An earlier
        # failed commit must not leave a readable phantom in this local mirror.
        restored = session_persistence.load_messages(session_id, user_id=user_id)
        revision = session_revision(state, session_id)
        if key not in self._store or self._revisions.get(key, "") != revision:
            self._revisions[key] = revision
            self._last_summary_time.pop(key, None)
            if restored:
                logger.info("message_count=%d %s", len(restored), memory_log_fields(
                    "history_restore", "completed", source_session_id=session_id))
        self._store[key] = self._copy(restored or [])
        return self._store[key]

    def _persist(self, session_id, user_id, state):
        key = cache_key(user_id, session_id)
        session_persistence.save_messages(session_id, self._store[key], user_id=user_id)
        self._revisions[key] = session_revision(state, session_id)

    def add_message(self, session_id: str, message: Message, *, user_id="default", delivery_id=None) -> List[Message]:
        with account_session(user_id, session_id=session_id) as state, self._lock:
            history = self._history(session_id, user_id, state)
            if delivery_id is not None and session_history.already_delivered(state, session_id, message, delivery_id):
                return self._copy(history)
            history.append(message.model_copy(deep=True))
            # Completion workers can arrive after later user turns. Timestamp
            # ordering preserves the conversation while receipts prevent replay.
            history.sort(key=lambda item: (item.role != "system", parse_utc(item.timestamp)))
            self._persist(session_id, user_id, state)
            if delivery_id is not None:
                session_history.record_delivery(state, session_id, message, delivery_id)
            return self._copy(history)

    def get_history(self, session_id: str, *, user_id="default") -> List[Message]:
        with account_session(user_id, session_id=session_id) as state, self._lock:
            return self._copy(self._history(session_id, user_id, state))

    def clear(self, session_id: str, *, user_id="default"):
        with account_session(user_id, cleanup=True), self._lock:
            key = cache_key(user_id, session_id)
            self._store.pop(key, None)
            self._revisions.pop(key, None)
            self._last_summary_time.pop(key, None)
            session_persistence.delete_session(session_id, user_id=user_id)

    def clear_user(self, user_id):
        with account_session(user_id, cleanup=True), self._lock:
            for key in list(self._store):
                if isinstance(key, tuple) and key[0] == str(user_id):
                    self._store.pop(key, None)
                    self._revisions.pop(key, None)
                    self._last_summary_time.pop(key, None)

    def should_summarize(self, session_id: str, *, user_id="default") -> bool:
        """判断是否需要摘要压缩。"""
        with account_session(user_id, session_id=session_id) as state, self._lock:
            history = self._copy(self._history(session_id, user_id, state))
            last_time = self._last_summary_time.get(cache_key(user_id, session_id))
        if len(history) <= KEEP_RECENT_COUNT:
            return False

        total_tokens = sum(m.token_count for m in history)
        if total_tokens <= settings.WORKING_MEMORY_MAX_TOKENS:
            return False

        if (
            last_time
            and (datetime.now() - last_time).total_seconds() < SUMMARY_COOLDOWN_SECONDS
        ):
            remaining = (
                SUMMARY_COOLDOWN_SECONDS - (datetime.now() - last_time).total_seconds()
            )
            logger.debug("remaining_seconds=%.0f %s", remaining, memory_log_fields(
                "summarize", "cooldown", source_session_id=session_id))
            return False

        return True

    def summarize(self, session_id: str, *, user_id="default", raise_on_error=False):
        """执行增量摘要压缩。"""
        with account_session(user_id, session_id=session_id) as state, self._lock:
            history = self._copy(self._history(session_id, user_id, state))
            revision = session_revision(state, session_id)
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
            "summarized_messages=%d summarized_tokens=%d retained_messages=%d retained_tokens=%d %s",
            len(to_summarize), sum(m.token_count for m in to_summarize),
            len(to_keep), sum(m.token_count for m in to_keep),
            memory_log_fields("summarize", "started", source_session_id=session_id),
        )

        history_text = "\n".join([f"{m.role}: {m.content}" for m in to_summarize])
        prompt = SUMMARY_PROMPT.format(history=history_text)

        try:
            response = llm.invoke(
                [
                    SystemMessage(content="你是一个对话摘要压缩器，只输出摘要内容。"),
                    HumanMessage(content=prompt),
                ]
            )
        except Exception as error:
            logger.error("error_type=%s %s", type(error).__name__, memory_log_fields(
                "summarize", "failed", source_session_id=session_id))
            if raise_on_error:
                raise RuntimeError("对话摘要暂时不可用，请重试记忆任务") from None
            return

        summary_msg = Message(
            role="system",
            content=f"[历史摘要] {response.content}",
            timestamp=utc_now().isoformat(),
            token_count=len(response.content) // 4,
        )

        # The model runs outside all locks. A newer turn, another worker,
        # clear or account deletion invalidates this captured result.
        with account_session(user_id, session_id=session_id) as state, self._lock:
            current = self._history(session_id, user_id, state)
            if session_revision(state, session_id) != revision or current != history:
                logger.info(memory_log_fields("summarize", "stale", source_session_id=session_id))
                return
            key = cache_key(user_id, session_id)
            self._store[key] = [summary_msg] + to_keep
            self._persist(session_id, user_id, state)
            self._last_summary_time[key] = datetime.now()
            new_total = sum(m.token_count for m in self._store[key])
        logger.info("token_count=%d %s", new_total, memory_log_fields(
            "summarize", "completed", source_session_id=session_id))


short_term_memory = ShortTermMemoryManager()
