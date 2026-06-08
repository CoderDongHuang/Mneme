import uuid
from datetime import datetime
from typing import List, Optional
from app.models.memory import MemoryEntry, Preference, WeakPoint, Progress
from app.core.logging import setup_logger

logger = setup_logger("long_term_memory")

class LongTermMemoryManager:
    def __init__(self):
        # 阶段二用内存存储，阶段三迁移到 Chroma
        self._preferences: dict = {}
        self._weak_points: dict = {}
        self._progress: dict = {}

    def add_preference(self, user_id: str, content: str) -> Preference:
        if user_id not in self._preferences:
            self._preferences[user_id] = []
        pref = Preference(
            id=str(uuid.uuid4()),
            content=content,
            created_at=datetime.now().isoformat()
        )
        self._preferences[user_id].append(pref)
        logger.info(f"用户 {user_id} 新增偏好: {content}")
        return pref

    def get_preferences(self, user_id: str) -> List[Preference]:
        return self._preferences.get(user_id, [])

    def add_weak_point(self, user_id: str, content: str, topic: str) -> WeakPoint:
        if user_id not in self._weak_points:
            self._weak_points[user_id] = []
        # 检查是否已存在相同薄弱点
        for wp in self._weak_points[user_id]:
            if wp.topic == topic:
                wp.count += 1
                return wp
        wp = WeakPoint(
            id=str(uuid.uuid4()),
            content=content,
            topic=topic,
            created_at=datetime.now().isoformat()
        )
        self._weak_points[user_id].append(wp)
        logger.info(f"用户 {user_id} 新增薄弱点: {topic}")
        return wp

    def get_weak_points(self, user_id: str) -> List[WeakPoint]:
        return self._weak_points.get(user_id, [])

    def update_progress(self, user_id: str, chapter: str, section: str):
        self._progress[user_id] = Progress(
            current_chapter=chapter,
            current_section=section,
            last_updated=datetime.now().isoformat()
        )
        logger.info(f"用户 {user_id} 学习进度更新: {chapter}/{section}")

    def get_progress(self, user_id: str) -> Optional[Progress]:
        return self._progress.get(user_id)

long_term_memory = LongTermMemoryManager()
