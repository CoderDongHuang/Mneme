"""
长期记忆管理器

职责：
- 管理用户的三类长期记忆：偏好(preference)、薄弱点(weak_point)、学习进度(progress)
- 通过 Chroma 向量库持久化存储，服务重启不丢失
- 内存缓存层加速热数据读取
- 写入时进行语义去重检查
"""
from datetime import datetime
from typing import List, Optional

from app.models.memory import Preference, WeakPoint, Progress
from app.memory.memory_store import memory_store
from app.core.logging import setup_logger

logger = setup_logger("long_term_memory")

# 缓存过期时间（秒）：超过此时间的缓存视为失效
CACHE_TTL_SECONDS = 300  # 5 分钟

# 每类记忆的存储上限
MAX_PREFERENCES = 30
MAX_WEAK_POINTS = 30

# 语义去重距离阈值（Chroma 距离，越小越相似）
DEDUP_THRESHOLD = 0.15


class LongTermMemoryManager:
    """长期记忆管理器（Chroma 持久化 + 内存缓存）

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
        """获取缓存，若过期返回 None"""
        bucket = self._cache.get(user_id, {}).get(category)
        if bucket is None:
            return None
        ts, data = bucket
        if (datetime.now() - ts).total_seconds() > CACHE_TTL_SECONDS:
            self._cache.get(user_id, {}).pop(category, None)
            return None
        return data

    def _set_cache(self, user_id: str, category: str, data):
        """写入缓存"""
        if user_id not in self._cache:
            self._cache[user_id] = {}
        self._cache[user_id][category] = (datetime.now(), data)

    def _invalidate_cache(self, user_id: str, category: Optional[str] = None):
        """使缓存失效，category 为 None 时清空该用户全部缓存"""
        if user_id not in self._cache:
            return
        if category:
            self._cache[user_id].pop(category, None)
        else:
            self._cache.pop(user_id, None)

    # ── 语义去重 ────────────────────────────────────────────

    def _is_duplicate(self, user_id: str, category: str, content: str) -> bool:
        """检查是否与已有记忆语义重复"""
        duplicates = self._store.find_duplicates(user_id, category, content, threshold=DEDUP_THRESHOLD)
        if duplicates:
            logger.info(f"语义去重命中: [{category}] '{content[:40]}...' 与已有记忆 '{duplicates[0]['content'][:40]}...' 重复 (dist={duplicates[0]['score']:.3f})")
            return True
        return False

    # ── 偏好 (Preference) ───────────────────────────────────

    def add_preference(self, user_id: str, content: str) -> Optional[str]:
        """添加用户偏好。语义去重通过后写入 Chroma。返回记忆 ID，重复时返回 None。"""
        # 语义去重
        if self._is_duplicate(user_id, "preference", content):
            return None

        # 数量检查
        existing = self._store.search(user_id, category="preference", top_k=MAX_PREFERENCES)
        if len(existing) >= MAX_PREFERENCES:
            # 淘汰 importance 最低的旧记忆
            oldest = min(existing, key=lambda e: e.get("importance", 0.5))
            self._store.delete_memory(oldest["id"])
            logger.info(f"偏好数量达上限({MAX_PREFERENCES})，淘汰最旧记忆: {oldest['content'][:40]}")

        mem_id = self._store.add_memory(user_id, "preference", content)
        self._invalidate_cache(user_id, "preferences")
        logger.info(f"用户 {user_id} 新增偏好: {content}")
        return mem_id

    def get_preferences(self, user_id: str) -> List[dict]:
        """获取用户所有偏好（优先从缓存读）"""
        cached = self._get_cached(user_id, "preferences")
        if cached is not None:
            return cached
        results = self._store.get_by_category(user_id, "preference", limit=MAX_PREFERENCES)
        self._set_cache(user_id, "preferences", results)
        return results

    def remove_preference(self, user_id: str, mem_id: str):
        """删除指定偏好"""
        self._store.delete_memory(mem_id)
        self._invalidate_cache(user_id, "preferences")

    # ── 薄弱点 (WeakPoint) ──────────────────────────────────

    def add_weak_point(self, user_id: str, content: str, topic: str) -> Optional[str]:
        """添加用户薄弱点。同 topic 会合并（增加计数），语义相似会去重。"""
        # 检查是否已有相同 topic 的薄弱点（精确匹配 → 累加计数）
        existing = self._store.get_by_category(user_id, "weak_point", limit=MAX_WEAK_POINTS)
        for entry in existing:
            if entry.get("topic") == topic:
                new_importance = min(1.0, entry.get("importance", 0.5) + 0.1)
                self._store.update_importance(entry["id"], new_importance)
                logger.info(f"薄弱点 '{topic}' 计数增加 (importance={new_importance:.1f})")
                self._invalidate_cache(user_id, "weak_points")
                return entry["id"]

        # 语义去重
        if self._is_duplicate(user_id, "weak_point", content):
            return None

        # 数量检查
        if len(existing) >= MAX_WEAK_POINTS:
            oldest = min(existing, key=lambda e: e.get("importance", 0.5))
            self._store.delete_memory(oldest["id"])
            logger.info(f"薄弱点数量达上限({MAX_WEAK_POINTS})，淘汰最旧记忆")

        mem_id = self._store.add_memory(
            user_id, "weak_point", content, topic=topic, importance=0.5
        )
        self._invalidate_cache(user_id, "weak_points")
        logger.info(f"用户 {user_id} 新增薄弱点: {topic}")
        return mem_id

    def get_weak_points(self, user_id: str) -> List[dict]:
        """获取用户所有薄弱点（优先从缓存读）"""
        cached = self._get_cached(user_id, "weak_points")
        if cached is not None:
            return cached
        results = self._store.get_by_category(user_id, "weak_point", limit=MAX_WEAK_POINTS)
        self._set_cache(user_id, "weak_points", results)
        return results

    def decay_weak_points(self, user_id: str):
        """薄弱点衰减：降低长时间未更新的薄弱点重要性"""
        weak_points = self._store.get_by_category(user_id, "weak_point", limit=MAX_WEAK_POINTS)
        now = datetime.now()
        for wp in weak_points:
            created_at = wp.get("created_at", "")
            if not created_at:
                continue
            try:
                created_time = datetime.fromisoformat(created_at)
                days_since = (now - created_time).days
                if days_since > 30:
                    new_importance = max(0.0, wp.get("importance", 0.5) - 0.2)
                    if new_importance <= 0.0:
                        self._store.delete_memory(wp["id"])
                        logger.info(f"薄弱点已过期删除: {wp.get('topic', '')}")
                    else:
                        self._store.update_importance(wp["id"], new_importance)
            except (ValueError, TypeError):
                pass
        self._invalidate_cache(user_id, "weak_points")

    # ── 学习进度 (Progress) ────────────────────────────────

    def update_progress(self, user_id: str, chapter: str, section: str):
        """更新用户学习进度。同一用户只保留最新一条进度记录。"""
        # 删除旧进度
        existing = self._store.get_by_category(user_id, "progress", limit=5)
        for entry in existing:
            self._store.delete_memory(entry["id"])

        content = f"学习进度: {chapter}/{section}"
        self._store.add_memory(user_id, "progress", content, topic=f"{chapter}/{section}")
        self._invalidate_cache(user_id, "progress")
        logger.info(f"用户 {user_id} 学习进度更新: {chapter}/{section}")

    def get_progress(self, user_id: str) -> Optional[dict]:
        """获取用户最新学习进度"""
        cached = self._get_cached(user_id, "progress")
        if cached is not None:
            return cached[0] if cached else None
        results = self._store.get_by_category(user_id, "progress", limit=1)
        if results:
            self._set_cache(user_id, "progress", results)
            return results[0]
        return None

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
