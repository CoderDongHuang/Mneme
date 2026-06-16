from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.memory.reflection import run_reflection
from app.memory.long_term_memory import long_term_memory
from app.memory.memory_store import memory_store
from app.core.logging import setup_logger

logger = setup_logger("reflection_scheduler")

# 记忆维护间隔（小时）
MEMORY_MAINTENANCE_INTERVAL_HOURS = 24


class ReflectionScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self._session_counts: dict = {}  # user_id -> session_count
        self._started = False

    def record_session(self, user_id: str):
        """记录会话次数"""
        self._session_counts[user_id] = self._session_counts.get(user_id, 0) + 1

    def check_and_trigger(self, user_id: str):
        """检查是否需要触发反思（每 5 次会话）"""
        if self._session_counts.get(user_id, 0) >= 5:
            logger.info(f"触发用户 {user_id} 的记忆反思")
            run_reflection(user_id)
            self._session_counts[user_id] = 0  # 重置计数

    def run_memory_maintenance(self):
        """定期记忆维护：衰减过时薄弱点、清理过期记忆。

        此方法由调度器每隔 MEMORY_MAINTENANCE_INTERVAL_HOURS 小时自动调用。
        """
        logger.info("开始定期记忆维护...")

        # 获取所有有记忆的用户
        user_ids = memory_store.list_users()
        if not user_ids:
            logger.info("记忆维护完成: 无用户需要处理")
            return

        decayed_total = 0
        for user_id in user_ids:
            try:
                before_count = memory_store.count_user_memories(user_id)
                long_term_memory.decay_weak_points(user_id)
                after_count = memory_store.count_user_memories(user_id)
                removed = before_count - after_count
                if removed > 0:
                    decayed_total += removed
                    logger.info(f"用户 {user_id}: 衰减删除 {removed} 条过时薄弱点")
            except Exception as e:
                logger.error(f"用户 {user_id} 记忆维护失败: {e}")

        logger.info(f"记忆维护完成: 处理 {len(user_ids)} 个用户, 删除 {decayed_total} 条过时记忆")

    def start(self):
        """启动调度器并注册定期任务"""
        if self._started:
            return
        self.scheduler.start()

        # 注册每日记忆维护任务（早 8:07，避开整点高峰）
        self.scheduler.add_job(
            self.run_memory_maintenance,
            trigger=IntervalTrigger(hours=MEMORY_MAINTENANCE_INTERVAL_HOURS),
            id="memory_maintenance",
            name="记忆衰减与过期清理",
            replace_existing=True,
        )
        logger.info(
            f"记忆反思调度器已启动 (维护间隔: {MEMORY_MAINTENANCE_INTERVAL_HOURS}h)"
        )
        self._started = True

    def shutdown(self):
        self.scheduler.shutdown()
        self._started = False


reflection_scheduler = ReflectionScheduler()
