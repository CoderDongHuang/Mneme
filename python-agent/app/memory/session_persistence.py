"""
会话消息 Redis 持久化层

解决短期记忆在服务重启后丢失的问题：
- 每次 add_message 时写入 Redis（TTL 24h）
- get_history 时优先从内存取，内存缺失时从 Redis 恢复
- Redis 不可用时自动降级为纯内存模式，不影响核心功能
"""
import json
import redis
import time
from datetime import datetime, timedelta
from typing import List, Optional

from app.models.chat import Message
from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("session_persistence")

SESSION_KEY_PREFIX = "mneme:session:"


class SessionPersistence:
    """会话消息 Redis 存储，自动降级"""

    def __init__(self):
        self._redis = None
        self._available = False
        self._last_attempt = 0.0
        self._init_redis()

    def _init_redis(self):
        self._last_attempt = time.monotonic()
        try:
            self._redis = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD or None,
                socket_connect_timeout=0.35,
                socket_timeout=0.5,
                decode_responses=True,
            )
            self._redis.ping()
            self._available = True
            logger.info(f"Redis 会话持久化已启用: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        except Exception as e:
            self._available = False
            logger.warning(f"Redis 不可用 ({e})，会话消息仅存在内存中")

    def _ensure_connection(self) -> bool:
        if self._available:
            return True
        if time.monotonic() - self._last_attempt >= 60:
            self._init_redis()
        return self._available

    def _session_key(self, session_id: str) -> str:
        return f"{SESSION_KEY_PREFIX}{session_id}"

    def save_messages(self, session_id: str, messages: List[Message]):
        if not self._ensure_connection():
            return
        try:
            data = json.dumps([
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "token_count": m.token_count,
                }
                for m in messages
            ], ensure_ascii=False)
            self._redis.setex(
                self._session_key(session_id),
                timedelta(hours=settings.SESSION_TTL_HOURS),
                data,
            )
        except Exception as e:
            logger.warning(f"Redis 会话保存失败: {e}")

    def load_messages(self, session_id: str) -> Optional[List[Message]]:
        if not self._ensure_connection():
            return None
        try:
            data = self._redis.get(self._session_key(session_id))
            if not data:
                return None
            raw_list = json.loads(data)
            return [
                Message(
                    role=m["role"],
                    content=m["content"],
                    timestamp=m.get("timestamp", datetime.now().isoformat()),
                    token_count=m.get("token_count", len(m["content"]) // 4),
                )
                for m in raw_list
            ]
        except Exception as e:
            logger.warning(f"Redis 会话恢复失败: {e}")
            return None

    def delete_session(self, session_id: str):
        if not self._ensure_connection():
            return
        try:
            self._redis.delete(self._session_key(session_id))
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._available


session_persistence = SessionPersistence()
