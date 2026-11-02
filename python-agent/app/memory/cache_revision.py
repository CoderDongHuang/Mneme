"""Durable shared revisions. Legacy Redis keys are only removed, never written."""
import redis

from app.core.config import settings
from app.knowledge.generations import generation_store, StaleGeneration


class MemoryCacheRevision:
    def __init__(self) -> None:
        self._redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            socket_connect_timeout=0.35,
            socket_timeout=0.5,
            decode_responses=True,
        )

    @staticmethod
    def from_state(state) -> int:
        if state.get("deleted"):
            raise StaleGeneration("账号已删除，拒绝读取或发布记忆缓存")
        revision = state.get("memory_cache_revision", 0)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("记忆缓存版本损坏")
        return revision

    def current(self, user_id: str) -> int:
        # Never fall back to process-local state after another replica mutates.
        return self.from_state(generation_store.snapshot(user_id))

    def bump(self, user_id: str) -> int:
        with generation_store.locked(user_id) as state:
            if state.get("deleted"):
                # Preserve the fence and fail cleanup if independent readback
                # fails. DEL returning normally is not evidence of erasure.
                try:
                    self._redis.delete(self._key(user_id))
                    if self._redis.exists(self._key(user_id)):
                        raise RuntimeError("旧记忆缓存版本删除后仍有残留")
                except Exception:
                    raise RuntimeError("无法确认旧记忆缓存版本已清理") from None
                return 0
            revision = self.from_state(state) + 1
            state["memory_cache_revision"] = revision
            return revision

    @staticmethod
    def _key(user_id: str) -> str:
        return f"mneme:memory-revision:{user_id}"

    def cleanup_deleted_revisions(self) -> int:
        """Upgrade maintenance: only erase keys with a durable tombstone.

        Failure is fatal and safe to retry. Active users and unrelated keys
        are never removed; bump rechecks the tombstone under the user lock.
        """
        prefix = "mneme:memory-revision:"
        removed = 0
        for key in self._redis.scan_iter(match=prefix + "*", count=250):
            user_id = key[len(prefix):]
            if not user_id or not generation_store.snapshot(user_id).get("deleted"):
                continue
            self.bump(user_id)
            removed += 1
        # An independent traversal also catches silent SCAN/DEL inconsistencies
        # visible to the Redis client. SCAN itself requires a trusted backend.
        for key in self._redis.scan_iter(match=prefix + "*", count=250):
            user_id = key[len(prefix):]
            if user_id and generation_store.snapshot(user_id).get("deleted"):
                raise RuntimeError("已删除账号仍有旧记忆缓存版本，请重试清理")
        return removed


memory_cache_revision = MemoryCacheRevision()
