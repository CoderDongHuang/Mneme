"""
会话历史以 SQL 为准，Redis 保存可丢弃的镜像（TTL 24h）。
首次读取旧 Redis 历史时在账号事务中迁移，无法读取旧历史时拒绝覆盖。
"""

import json
import redis
import time
from hashlib import sha256
from datetime import timedelta
from typing import List, Optional

from app.core.time import utc_now
from app.models.chat import Message
from app.core.config import settings
from app.core.logging import setup_logger, memory_log_fields
from app.memory.session_scope import account_session, advance_revision, session_revision
from app.memory import session_history

logger = setup_logger("session_persistence")

SESSION_KEY_PREFIX = "mneme:session:"


class SessionPersistence:
    """SQL history with an optional Redis mirror and strict cleanup."""

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
            logger.info(memory_log_fields("session_connect", "ready"))
        except Exception as error:
            self._available = False
            logger.warning("error_type=%s %s", type(error).__name__,
                           memory_log_fields("session_connect", "sql_only"))

    def _ensure_connection(self) -> bool:
        if self._available:
            return True
        if time.monotonic() - self._last_attempt >= 60:
            self._init_redis()
        return self._available

    @staticmethod
    def _user_prefix(user_id):
        return f"{SESSION_KEY_PREFIX}v2:{sha256(str(user_id).encode()).hexdigest()}:"

    def _session_key(self, session_id: str, user_id="default") -> str:
        if str(user_id) == "default":
            return f"{SESSION_KEY_PREFIX}{session_id}"
        return self._user_prefix(user_id) + sha256(session_id.encode()).hexdigest()

    def _cleanup_keys(self, session_id, user_id):
        return list(dict.fromkeys([self._session_key(session_id, user_id), self._session_key(session_id)]))

    def save_messages(self, session_id: str, messages: List[Message], *, user_id="default"):
        with account_session(user_id, session_id=session_id) as state:
            session_history.save(state, session_id, messages)
            revision = advance_revision(state, session_id)
            if not self._ensure_connection():
                return
            try:
                data = json.dumps({"revision": revision, "messages": [m.model_dump() for m in messages]}, ensure_ascii=False)
                self._redis.setex(self._session_key(session_id, user_id),
                                  timedelta(hours=settings.SESSION_TTL_HOURS), data)
            except Exception as error:
                self._available = False
                logger.warning("error_type=%s %s", type(error).__name__, memory_log_fields(
                    "session_save", "sql_only", source_session_id=session_id))

    def load_messages(self, session_id: str, *, user_id="default") -> Optional[List[Message]]:
        with account_session(user_id, session_id=session_id) as state:
            durable = session_history.bucket(state, session_id)
            if durable is not None:
                return session_history.messages(durable)
            revision = session_revision(state, session_id)
            from app.memory.session_store import session_store
            try:
                legacy_owner = str(user_id) != "default" and session_store.owns_legacy_cache(user_id, session_id)
            except Exception:
                raise RuntimeError("旧会话清单暂不可用，请修复后重试") from None
            if not self._ensure_connection():
                if revision or legacy_owner:
                    raise RuntimeError("旧会话历史暂不可用，请恢复 Redis 后重试")
                return None
            data = None
            try:
                data = self._redis.get(self._session_key(session_id, user_id))
                if not data and not revision and str(user_id) != "default":
                    # Legacy IDs are globally canonical Gateway IDs. Never
                    # guess ownership or read an unregistered user's old key.
                    if legacy_owner:
                        data = self._redis.get(self._session_key(session_id))
                if not data:
                    if revision:
                        raise RuntimeError("旧会话历史暂不可用，请恢复 Redis 后重试")
                    return None
                payload = json.loads(data)
                if isinstance(payload, dict):
                    if payload.get("revision") != revision:
                        raise RuntimeError("旧会话历史暂不可用，请恢复 Redis 后重试")
                    raw_list = payload["messages"]
                elif isinstance(payload, list) and not revision:
                    raw_list = payload
                else:
                    raise ValueError("旧会话历史格式无效")
                restored = [Message(role=m["role"], content=m["content"],
                                timestamp=m.get("timestamp", utc_now().isoformat()),
                                token_count=m.get("token_count", len(m["content"]) // 4)) for m in raw_list]
            except Exception as error:
                self._available = False
                logger.warning("error_type=%s %s", type(error).__name__, memory_log_fields(
                    "session_load", "unavailable", source_session_id=session_id))
                if revision or legacy_owner or data:
                    raise RuntimeError("旧会话历史暂不可用，请恢复 Redis 后重试") from None
                return None
            # Outside the Redis exception handler: a failed SQL commit must
            # propagate, never be mislabeled as successful cache degradation.
            session_history.save(state, session_id, restored)
            return restored

    def delete_session(self, session_id: str, *, user_id="default"):
        with account_session(user_id, cleanup=True) as state:
            session_history.clear(state, session_id)
            advance_revision(state, session_id)
            if not self._ensure_connection():
                raise RuntimeError("Redis 不可用，无法确认会话数据已删除")
            try:
                for key in self._cleanup_keys(session_id, user_id):
                    self._redis.delete(key)
                if self.count_sessions([session_id], user_id=user_id) != 0:
                    raise RuntimeError("Redis 会话删除后仍有残留")
            except Exception as error:
                self._available = False
                logger.warning("error_type=%s %s", type(error).__name__, memory_log_fields(
                    "session_delete", "failed", source_session_id=session_id))
                raise RuntimeError("Redis 会话删除失败") from None

    def count_sessions(self, session_ids: list[str], *, user_id="default") -> int:
        if not session_ids:
            return 0
        if not self._ensure_connection():
            raise RuntimeError("Redis 不可用，无法核验会话残留")
        try:
            keys = list(dict.fromkeys(key for sid in session_ids for key in self._cleanup_keys(sid, user_id)))
            return self._redis.exists(*keys)
        except Exception as error:
            self._available = False
            logger.warning("error_type=%s session_count=%d %s", type(error).__name__, len(session_ids),
                           memory_log_fields("session_count", "failed"))
            raise RuntimeError("Redis 会话读回失败") from None

    def count_user_sessions(self, user_id) -> int:
        if not self._ensure_connection():
            raise RuntimeError("Redis 不可用，无法核验会话残留")
        return sum(1 for _ in self._redis.scan_iter(match=self._user_prefix(user_id) + "*", count=200))

    def delete_user_sessions(self, user_id):
        """Erase scoped orphans too; legacy IDs use the canonical batch API."""
        with account_session(user_id, cleanup=True) as state:
            if not state.get("deleted"):
                raise RuntimeError("账号未停止写入，拒绝整批清理会话缓存")
            state.pop("session_histories", None)
            state.pop("memory_completions", None)
            if not self._ensure_connection():
                raise RuntimeError("Redis 不可用，无法核验会话残留")
            try:
                prefix = self._user_prefix(user_id)
                for key in self._redis.scan_iter(match=prefix + "*", count=200):
                    self._redis.delete(key)
                if next(iter(self._redis.scan_iter(match=prefix + "*", count=200)), None) is not None:
                    raise RuntimeError("Redis 账号会话删除后仍有残留")
            except Exception as error:
                self._available = False
                logger.warning("error_type=%s %s", type(error).__name__, memory_log_fields("session_user_delete", "failed"))
                raise RuntimeError("Redis 账号会话删除失败") from None

    @property
    def available(self) -> bool:
        return self._available


session_persistence = SessionPersistence()
