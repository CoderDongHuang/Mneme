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

    def get_all_sessions(self, user_id: str = "default") -> List[dict]:
        """获取所有会话列表（返回摘要信息）"""
        sessions = []
        for session_id, messages in self._store.items():
            if messages:
                # 取第一条消息作为标题
                first_msg = messages[0]
                title = first_msg.content[:30] + ("..." if len(first_msg.content) > 30 else "")
                # 取最后一条消息的时间
                last_msg = messages[-1]
                sessions.append({
                    "id": session_id,
                    "title": title,
                    "message_count": len(messages),
                    "last_updated": last_msg.timestamp
                })
        # 按时间倒序
        sessions.sort(key=lambda x: x["last_updated"], reverse=True)
        return sessions

working_memory = WorkingMemoryManager()
