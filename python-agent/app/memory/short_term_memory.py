from typing import List
from app.models.chat import Message
from app.utils.llm import llm
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import settings
from datetime import datetime
from app.core.logging import setup_logger

logger = setup_logger("short_term_memory")

SUMMARY_PROMPT = """请对以下对话历史进行摘要压缩，保留核心信息和关键知识点：

{history}

请用简洁的语言输出摘要。"""

class ShortTermMemoryManager:
    def __init__(self):
        self._store: dict = {}  # session_id -> full_history

    def add_message(self, session_id: str, message: Message) -> List[Message]:
        if session_id not in self._store:
            self._store[session_id] = []
        self._store[session_id].append(message)
        return self._store[session_id]

    def get_history(self, session_id: str) -> List[Message]:
        return self._store.get(session_id, [])

    def clear(self, session_id: str):
        self._store.pop(session_id, None)

    def should_summarize(self, session_id: str) -> bool:
        """判断是否需要摘要压缩（token 阈值触发）"""
        history = self._store.get(session_id, [])
        total_tokens = sum(m.token_count for m in history)
        return total_tokens > settings.WORKING_MEMORY_MAX_TOKENS

    def summarize(self, session_id: str):
        """执行摘要压缩"""
        history = self._store.get(session_id, [])
        if not history:
            return

        history_text = "\n".join([f"{m.role}: {m.content}" for m in history])
        prompt = SUMMARY_PROMPT.format(history=history_text)
        response = llm.invoke([
            SystemMessage(content="你是一个对话摘要压缩器。"),
            HumanMessage(content=prompt)
        ])

        # 保留摘要 + 最近 3 条消息
        summary_msg = Message(
            role="system",
            content=f"[摘要] {response.content}",
            timestamp=datetime.now().isoformat(),
            token_count=len(response.content) // 4
        )
        self._store[session_id] = [summary_msg] + history[-3:]
        logger.info(f"会话 {session_id} 摘要压缩完成")

short_term_memory = ShortTermMemoryManager()
