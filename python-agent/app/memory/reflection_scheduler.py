from apscheduler.schedulers.background import BackgroundScheduler
from app.memory.reflection import run_reflection
from app.core.logging import setup_logger

logger = setup_logger("reflection_scheduler")

class ReflectionScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self._session_counts: dict = {}  # user_id -> session_count

    def record_session(self, user_id: str):
        """记录会话次数"""
        self._session_counts[user_id] = self._session_counts.get(user_id, 0) + 1

    def check_and_trigger(self, user_id: str):
        """检查是否需要触发反思（每 5 次会话）"""
        if self._session_counts.get(user_id, 0) >= 5:
            logger.info(f"触发用户 {user_id} 的记忆反思")
            run_reflection(user_id)
            self._session_counts[user_id] = 0  # 重置计数

    def start(self):
        self.scheduler.start()
        logger.info("记忆反思调度器已启动")

    def shutdown(self):
        self.scheduler.shutdown()

reflection_scheduler = ReflectionScheduler()
