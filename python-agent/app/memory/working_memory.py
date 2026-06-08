from typing import List
from app.models.chat import Message
from app.core.config import settings

class WorkingMemoryManager:
    def __init__(self):
        self._store: dict = {}  # session_id -> messages

    def add_message(self, session_id: str, message: Message) -> List[Message]:
        if session_id not in self._store:
            self._store[session_id] = []
        self._store[session_id].append(message)

        # 滑动窗口：保留最近 window_size 条消息
        window_size = settings.WORKING_MEMORY_WINDOW_SIZE
        if len(self._store[session_id]) > window_size:
            self._store[session_id] = self._store[session_id][-window_size:]

        return self._store[session_id]

    def get_messages(self, session_id: str) -> List[Message]:
        return self._store.get(session_id, [])

    def clear(self, session_id: str):
        self._store.pop(session_id, None)

working_memory = WorkingMemoryManager()
