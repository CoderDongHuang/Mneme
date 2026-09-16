import threading
import time

import redis

from app.core.config import settings


class MemoryCacheRevision:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._local: dict[str, int] = {}
        self._available: bool | None = None
        self._last_failure = 0.0
        self._redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            decode_responses=True,
        )

    def current(self, user_id: str) -> int:
        local = self._local.get(user_id, 0)
        if not self._can_try_remote():
            return local
        try:
            remote = int(self._redis.get(self._key(user_id)) or 0)
            self._available = True
            return max(local, remote)
        except redis.RedisError:
            self._mark_failure()
            return local

    def bump(self, user_id: str) -> int:
        with self._lock:
            local = self._local.get(user_id, 0) + 1
            self._local[user_id] = local
        if not self._can_try_remote():
            return local
        try:
            remote = int(self._redis.incr(self._key(user_id)))
            self._redis.expire(self._key(user_id), 7 * 24 * 60 * 60)
            self._available = True
            return max(local, remote)
        except redis.RedisError:
            self._mark_failure()
            return local

    def _can_try_remote(self) -> bool:
        return self._available is not False or time.monotonic() - self._last_failure >= 60

    def _mark_failure(self) -> None:
        self._available = False
        self._last_failure = time.monotonic()

    def _key(self, user_id: str) -> str:
        return f"mneme:memory-revision:{user_id}"


memory_cache_revision = MemoryCacheRevision()
