"""
长期记忆管理器

职责：
- 管理用户的三类长期记忆：偏好(preference)、薄弱点(weak_point)、学习进度(progress)
- 通过 Qdrant 向量库持久化存储，服务重启不丢失
- 内存缓存层加速热数据读取
- 写入时进行语义去重检查
"""

from datetime import datetime
from copy import deepcopy
from typing import List, Optional

from app.core.time import utc_now, parse_utc
from app.memory.memory_store import memory_store
from app.core.logging import setup_logger, memory_log_fields
from app.memory.cache_revision import memory_cache_revision
from app.knowledge.generations import generation_store

logger = setup_logger("long_term_memory")

# 缓存过期时间（秒）：超过此时间的缓存视为失效
CACHE_TTL_SECONDS = 300  # 5 分钟

# 每类记忆的存储上限
MAX_PREFERENCES = 30
MAX_WEAK_POINTS = 30

# 语义去重距离阈值（Qdrant 距离，越小越相似）
DEDUP_THRESHOLD = 0.15


class LongTermMemoryManager:
    """长期记忆管理器（Qdrant 持久化 + 内存缓存）

    使用方式：
        from app.memory.long_term_memory import long_term_memory
        long_term_memory.add_preference(user_id, "喜欢图表讲解")
    """

    def __init__(self):
        self._store = memory_store
        # 内存缓存: user_id → { "preferences": (timestamp, list), "weak_points": (timestamp, list), ... }
        self._cache: dict = {}

    # ── 缓存辅助 ────────────────────────────────────────────

    def _get_cached(self, user_id: str, category: str) -> Optional[tuple]:
        """Validate shared state even on hits; never expose mutable cache data."""
        with generation_store.locked(user_id) as state:
            if state.get("deleted"):
                self._cache.pop(user_id, None)
            revision = memory_cache_revision.from_state(state)
            bucket = self._cache.get(user_id, {}).get(category)
            if bucket is None:
                return None
            ts, cached_revision, data = bucket
            if ((datetime.now() - ts).total_seconds() > CACHE_TTL_SECONDS
                    or cached_revision != revision):
                self._cache.get(user_id, {}).pop(category, None)
                return None
            return deepcopy(data)

    def _set_cache(self, user_id: str, category: str, data, expected_revision: int):
        with generation_store.locked(user_id) as state:
            if state.get("deleted"):
                self._cache.pop(user_id, None)
            revision = memory_cache_revision.from_state(state)
            if revision != expected_revision:
                return False
            self._cache.setdefault(user_id, {})[category] = (
                datetime.now(), revision, deepcopy(data)
            )
            return True

    def _read_category(self, user_id: str, category: str, cache_key: str, limit: int):
        cached = self._get_cached(user_id, cache_key)
        if cached is not None:
            return cached
        for _ in range(3):
            revision = memory_cache_revision.current(user_id)
            # Provider/storage work holds no account lock; validate on publish.
            results = self._store.get_by_category(user_id, category, limit=limit)
            if self._set_cache(user_id, cache_key, results, revision):
                return deepcopy(results)
        raise RuntimeError("记忆正在更新，请重试读取")

    def _invalidate_cache(self, user_id: str, category: Optional[str] = None):
        """使缓存失效，category 为 None 时清空该用户全部缓存"""
        try:
            memory_cache_revision.bump(user_id)
        finally:
            # Evict locally even if shared state or legacy key cleanup fails.
            if category:
                self._cache.get(user_id, {}).pop(category, None)
            else:
                self._cache.pop(user_id, None)

    # ── 语义去重 ────────────────────────────────────────────

    def _is_duplicate(self, user_id: str, category: str, content: str) -> bool:
        """检查是否与已有记忆语义重复"""
        duplicates = self._store.find_duplicates(
            user_id, category, content, threshold=DEDUP_THRESHOLD
        )
        if duplicates:
            logger.info(memory_log_fields("deduplicate", "matched", user_id=user_id,
                        category=category, memory_id=duplicates[0].get("id", ""), content=content))
            return True
        return False

    # ── 偏好 (Preference) ───────────────────────────────────

    def add_preference(
        self, user_id: str, content: str, source_session_id: str = "",
        evidence_hashes: list[str] | None = None
    ) -> Optional[str]:
        """添加用户偏好。语义去重通过后写入 Qdrant。返回记忆 ID，重复时返回 None。"""
        # 语义去重
        if self._is_duplicate(user_id, "preference", content):
            return None

        # 数量检查
        existing = self._store.search(
            user_id, category="preference", top_k=MAX_PREFERENCES
        )
        if len(existing) >= MAX_PREFERENCES:
            # 淘汰 importance 最低的旧记忆
            oldest = min(existing, key=lambda e: e.get("importance", 0.5))
            self._store.delete_memory(oldest["id"])
            logger.info(memory_log_fields("evict", "deleted", user_id=user_id,
                        category="preference", memory_id=oldest["id"]))

        mem_id = self._store.add_memory(
            user_id, "preference", content,
            source_session_id=source_session_id, evidence_hashes=evidence_hashes,
        )
        self._invalidate_cache(user_id, "preferences")
        logger.info(memory_log_fields("write", "stored", user_id=user_id, memory_id=mem_id,
                    category="preference", content=content, source_session_id=source_session_id))
        return mem_id

    def get_preferences(self, user_id: str) -> List[dict]:
        """获取用户所有偏好（优先从缓存读）"""
        return self._read_category(user_id, "preference", "preferences", MAX_PREFERENCES)

    def remove_preference(self, user_id: str, mem_id: str):
        """删除指定偏好"""
        self._store.delete_memory(mem_id)
        self._invalidate_cache(user_id, "preferences")

    # ── 薄弱点 (WeakPoint) ──────────────────────────────────

    def add_weak_point(
        self, user_id: str, content: str, topic: str,
        source_session_id: str = "", evidence_hashes: list[str] | None = None
    ) -> Optional[str]:
        """添加用户薄弱点。同 topic 会合并（增加计数），语义相似会去重。"""
        # 检查是否已有相同 topic 的薄弱点（精确匹配 → 累加计数）
        existing = self._store.get_by_category(
            user_id, "weak_point", limit=MAX_WEAK_POINTS
        )
        for entry in existing:
            if entry.get("topic") == topic:
                new_importance = min(1.0, entry.get("importance", 0.5) + 0.1)
                self._store.update_importance(entry["id"], new_importance)
                logger.info(memory_log_fields("reinforce", "updated", user_id=user_id,
                            category="weak_point", memory_id=entry["id"], content=content,
                            source_session_id=source_session_id))
                self._invalidate_cache(user_id, "weak_points")
                return entry["id"]

        # 语义去重
        if self._is_duplicate(user_id, "weak_point", content):
            return None

        # 数量检查
        if len(existing) >= MAX_WEAK_POINTS:
            oldest = min(existing, key=lambda e: e.get("importance", 0.5))
            self._store.delete_memory(oldest["id"])
            logger.info(memory_log_fields("evict", "deleted", user_id=user_id,
                        category="weak_point", memory_id=oldest["id"]))

        mem_id = self._store.add_memory(
            user_id, "weak_point", content, topic=topic, importance=0.5,
            source_session_id=source_session_id, evidence_hashes=evidence_hashes,
        )
        self._invalidate_cache(user_id, "weak_points")
        logger.info(memory_log_fields("write", "stored", user_id=user_id, memory_id=mem_id,
                    category="weak_point", content=content, source_session_id=source_session_id))
        return mem_id

    def get_weak_points(self, user_id: str) -> List[dict]:
        """获取用户所有薄弱点（优先从缓存读）"""
        return self._read_category(user_id, "weak_point", "weak_points", MAX_WEAK_POINTS)

    def decay_weak_points(self, user_id: str):
        """薄弱点衰减：降低长时间未更新的薄弱点重要性"""
        weak_points = self._store.get_by_category(
            user_id, "weak_point", limit=MAX_WEAK_POINTS
        )
        now = utc_now()
        for wp in weak_points:
            created_at = wp.get("created_at", "")
            if not created_at:
                continue
            try:
                created_time = parse_utc(created_at)
                days_since = (now - created_time).days
                if days_since > 30:
                    new_importance = max(0.0, wp.get("importance", 0.5) - 0.2)
                    if new_importance <= 0.0:
                        self._store.delete_memory(wp["id"])
                        logger.info(memory_log_fields("decay", "deleted", user_id=user_id,
                                    category="weak_point", memory_id=wp["id"]))
                    else:
                        self._store.update_importance(wp["id"], new_importance)
            except (ValueError, TypeError):
                pass
        self._invalidate_cache(user_id, "weak_points")

    # ── 学习进度 (Progress) ────────────────────────────────

    def update_progress(
        self, user_id: str, chapter: str, section: str,
        source_session_id: str = "", evidence_hashes: list[str] | None = None
    ):
        """更新用户学习进度。同一用户只保留最新一条进度记录。"""
        # 删除旧进度
        existing = self._store.get_by_category(user_id, "progress", limit=5)
        for entry in existing:
            self._store.delete_memory(entry["id"])

        content = f"学习进度: {chapter}/{section}"
        mem_id = self._store.add_memory(
            user_id, "progress", content, topic=f"{chapter}/{section}",
            source_session_id=source_session_id, evidence_hashes=evidence_hashes,
        )
        self._invalidate_cache(user_id, "progress")
        logger.info(memory_log_fields("write", "stored", user_id=user_id, memory_id=mem_id,
                    category="progress", content=content, source_session_id=source_session_id))

    def get_progress(self, user_id: str) -> Optional[dict]:
        """获取用户最新学习进度"""
        results = self._read_category(user_id, "progress", "progress", 1)
        return results[0] if results else None

    def get_progress_history(self, user_id: str) -> List[dict]:
        """获取用户进度变更历史"""
        return self._store.get_by_category(user_id, "progress", limit=50)

    # ── 综合查询 ────────────────────────────────────────────

    def get_all_memories(self, user_id: str) -> dict:
        """获取用户所有记忆的快照"""
        return {
            "preferences": self.get_preferences(user_id),
            "weak_points": self.get_weak_points(user_id),
            "progress": self.get_progress(user_id),
        }

    def delete_user_all(self, user_id: str):
        """删除用户全部长期记忆"""
        self._store.delete_user_memories(user_id)
        self._invalidate_cache(user_id)

    def get_memory_count(self, user_id: str) -> int:
        """统计用户记忆总数"""
        return self._store.count_user_memories(user_id)


# 全局单例——保持与旧代码一致的模块级变量名
long_term_memory = LongTermMemoryManager()
