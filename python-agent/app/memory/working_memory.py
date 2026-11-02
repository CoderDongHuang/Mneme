from typing import List
from threading import RLock
from app.models.chat import Message
from app.core.config import settings
from app.memory.session_scope import account_session, cache_key


class WorkingMemoryManager:
    def __init__(self):
        self._store: dict = {}  # session_id -> messages
        self._lock = RLock()

    def add_message(self, session_id: str, message: Message, *, user_id="default") -> List[Message]:
        with account_session(user_id), self._lock:
            key = cache_key(user_id, session_id)
            history = self._store.setdefault(key, [])
            history.append(message.model_copy(deep=True))

            window_size = settings.WORKING_MEMORY_WINDOW_SIZE
            self._store[key] = history[-window_size:]
            return [item.model_copy(deep=True) for item in self._store[key]]

    def get_messages(self, session_id: str, *, user_id="default") -> List[Message]:
        with account_session(user_id), self._lock:
            return [item.model_copy(deep=True) for item in self._store.get(cache_key(user_id, session_id), [])]

    def clear(self, session_id: str, *, user_id="default"):
        with account_session(user_id, cleanup=True), self._lock:
            self._store.pop(cache_key(user_id, session_id), None)

    def clear_user(self, user_id):
        with account_session(user_id, cleanup=True), self._lock:
            for key in list(self._store):
                if isinstance(key, tuple) and key[0] == str(user_id):
                    self._store.pop(key, None)

    def get_all_sessions(self, user_id: str = "default") -> List[dict]:
        """获取所有会话列表（返回摘要信息）"""
        with account_session(user_id), self._lock:
            owned = [(key[1] if isinstance(key, tuple) else key, messages)
                     for key, messages in self._store.items()
                     if (key[0] if isinstance(key, tuple) else "default") == str(user_id)]
            return self._session_summaries(owned)

    @staticmethod
    def _session_summaries(owned):
        sessions = []
        for session_id, messages in owned:
            if messages:
                # 取第一条消息作为标题
                first_msg = messages[0]
                title = first_msg.content[:30] + (
                    "..." if len(first_msg.content) > 30 else ""
                )
                # 取最后一条消息的时间
                last_msg = messages[-1]
                sessions.append(
                    {
                        "id": session_id,
                        "title": title,
                        "message_count": len(messages),
                        "last_updated": last_msg.timestamp,
                    }
                )
        # 按时间倒序
        sessions.sort(key=lambda x: x["last_updated"], reverse=True)
        return sessions


working_memory = WorkingMemoryManager()
