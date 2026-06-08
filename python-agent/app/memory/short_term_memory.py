from typing import List
from app.models.chat import Message

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

short_term_memory = ShortTermMemoryManager()
