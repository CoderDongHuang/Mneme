"""
会话元数据持久化存储

将 session 基本信息（标题、消息数、最后更新时间）持久化到 JSON 文件，
服务重启后历史对话列表不丢失。

设计：
- 每个用户的会话元数据存储在一个 JSON 文件中
- 线程安全：使用 threading.Lock 保护写操作
- 自动清理：删除过期会话（默认 30 天无活动）
"""
import json
import os
import threading
from datetime import datetime, timedelta
from typing import List, Dict

from app.core.logging import setup_logger

logger = setup_logger("session_store")

# 数据文件路径
DATA_DIR = "./data/sessions"
SESSION_TTL_DAYS = 30  # 会话保留天数


class SessionStore:
    """会话元数据持久化存储"""

    def __init__(self, data_dir: str = DATA_DIR):
        self._data_dir = data_dir
        self._lock = threading.Lock()
        os.makedirs(self._data_dir, exist_ok=True)

    def _get_file_path(self, user_id: str) -> str:
        """获取用户会话文件路径"""
        safe_name = user_id.replace("/", "_").replace("\\", "_")
        return os.path.join(self._data_dir, f"{safe_name}.json")

    def _load(self, user_id: str) -> Dict[str, Dict]:
        """从 JSON 文件加载用户会话数据"""
        file_path = self._get_file_path(user_id)
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"会话文件损坏，重新创建: {file_path}, error={e}")
            return {}

    def _save(self, user_id: str, data: Dict[str, Dict]):
        """保存用户会话数据到 JSON 文件"""
        file_path = self._get_file_path(user_id)
        with self._lock:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except IOError as e:
                logger.error(f"会话数据写入失败: {file_path}, error={e}")

    def register_session(
        self,
        user_id: str,
        session_id: str,
        title: str = "",
        message_count: int = 0
    ):
        """注册或更新会话。首次注册时自动生成标题。"""
        data = self._load(user_id)

        now = datetime.now().isoformat()
        if session_id in data:
            # 更新已有会话
            existing = data[session_id]
            existing["message_count"] = message_count or existing.get("message_count", 0) + 1
            existing["last_updated"] = now
            if title and existing.get("title", "").startswith("新对话"):
                existing["title"] = title
        else:
            # 新建会话
            data[session_id] = {
                "user_id": user_id,
                "title": title or "新对话",
                "message_count": max(message_count, 1),
                "created_at": now,
                "last_updated": now,
            }

        self._save(user_id, data)

    def update_title(self, user_id: str, session_id: str, title: str):
        """更新会话标题（如用第一条用户消息做标题）"""
        data = self._load(user_id)
        if session_id in data:
            data[session_id]["title"] = title[:50]
            data[session_id]["last_updated"] = datetime.now().isoformat()
            self._save(user_id, data)

    def increment_message_count(self, user_id: str, session_id: str):
        """消息计数 +1"""
        data = self._load(user_id)
        if session_id in data:
            data[session_id]["message_count"] = data[session_id].get("message_count", 0) + 1
            data[session_id]["last_updated"] = datetime.now().isoformat()
            self._save(user_id, data)

    def get_sessions(self, user_id: str) -> List[Dict]:
        """获取用户所有会话列表（按时间倒序）"""
        data = self._load(user_id)

        # 清理过期会话
        cutoff = datetime.now() - timedelta(days=SESSION_TTL_DAYS)
        expired = []
        for sid, info in data.items():
            try:
                last_updated = datetime.fromisoformat(info.get("last_updated", ""))
                if last_updated < cutoff:
                    expired.append(sid)
            except (ValueError, TypeError):
                pass

        for sid in expired:
            logger.info(f"清理过期会话: {sid}")
            del data[sid]

        if expired:
            self._save(user_id, data)

        sessions = [
            {
                "id": sid,
                "title": info.get("title", "新对话"),
                "message_count": info.get("message_count", 0),
                "last_updated": info.get("last_updated", ""),
            }
            for sid, info in data.items()
        ]
        sessions.sort(key=lambda s: s["last_updated"], reverse=True)
        return sessions

    def delete_session(self, user_id: str, session_id: str):
        """删除指定会话"""
        data = self._load(user_id)
        if session_id in data:
            del data[session_id]
            self._save(user_id, data)
            logger.info(f"会话已删除: {session_id}")

    def get_session_count(self, user_id: str) -> int:
        """获取用户会话数量"""
        return len(self._load(user_id))


# 全局单例
session_store = SessionStore()
