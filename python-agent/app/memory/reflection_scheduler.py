from concurrent.futures import ThreadPoolExecutor
import uuid

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.memory.reflection import run_reflection
from app.memory.long_term_memory import long_term_memory
from app.memory.memory_store import memory_store
from app.core.logging import setup_logger
from app.core.config import settings

logger = setup_logger("reflection_scheduler")

MEMORY_MAINTENANCE_INTERVAL_HOURS = 24

# 异步执行反思，不阻塞聊天请求线程
_reflection_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="reflection"
)

_COUNTER_PREFIX = "mneme:reflection:sessions:"
_LEASE_PREFIX = "mneme:reflection:lease:"
_COMPLETE_SCRIPT = """
if redis.call('get', KEYS[2]) ~= ARGV[1] then return 0 end
local current = tonumber(redis.call('get', KEYS[1]) or '0')
local claimed = tonumber(ARGV[2])
local remaining = current - claimed
if remaining > 0 then redis.call('set', KEYS[1], remaining) else redis.call('del', KEYS[1]) end
redis.call('del', KEYS[2])
return 1
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end
"""


class ReflectionScheduler:
    def __init__(self, redis_client=None, executor=None):
        self.scheduler = BackgroundScheduler()
        self._session_counts: dict[str, int] = {}
        self._local_leases: set[str] = set()
        self._redis = redis_client or redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            socket_connect_timeout=0.25,
            socket_timeout=0.5,
            decode_responses=True,
        )
        self._redis_available = redis_client is not None
        self._executor = executor or _reflection_executor
        self._started = False

    def _counter_key(self, user_id: str) -> str:
        return f"{_COUNTER_PREFIX}{user_id}"

    def _lease_key(self, user_id: str) -> str:
        return f"{_LEASE_PREFIX}{user_id}"

    def record_session(self, user_id: str) -> int:
        """Increment shared state atomically, falling back only for local development."""
        try:
            count = int(self._redis.incr(self._counter_key(user_id)))
            if count == 1:
                self._redis.expire(self._counter_key(user_id), 7 * 24 * 60 * 60)
            self._redis_available = True
            return count
        except redis.RedisError:
            self._redis_available = False
            self._session_counts[user_id] = self._session_counts.get(user_id, 0) + 1
            return self._session_counts[user_id]

    def check_and_trigger(self, user_id: str) -> bool:
        """Use a Redis lease so only one node submits a reflection job."""
        threshold = settings.memory_reflection_every_sessions
        try:
            count = int(self._redis.get(self._counter_key(user_id)) or 0)
            self._redis_available = True
            if count < threshold:
                return False
            lease_token = uuid.uuid4().hex
            acquired = self._redis.set(
                self._lease_key(user_id),
                lease_token,
                nx=True,
                ex=max(60, settings.memory_reflection_lease_seconds),
            )
            if not acquired:
                return False
            shared = True
        except redis.RedisError:
            self._redis_available = False
            count = self._session_counts.get(user_id, 0)
            if count < threshold or user_id in self._local_leases:
                return False
            lease_token = "local"
            self._local_leases.add(user_id)
            shared = False
        logger.info("触发用户 %s 的记忆反思（异步）", user_id)
        self._executor.submit(
            self._run_reflection_safe, user_id, count, lease_token, shared
        )
        return True

    def _run_reflection_safe(
        self, user_id: str, claimed_count: int = 0, lease_token: str = "", shared: bool = False
    ):
        """在线程池中执行反思，捕获所有异常避免线程静默死亡"""
        try:
            run_reflection(user_id)
            if shared:
                self._complete_shared(user_id, claimed_count, lease_token)
            else:
                self._session_counts[user_id] = max(
                    0, self._session_counts.get(user_id, 0) - claimed_count
                )
                self._local_leases.discard(user_id)
            logger.info("用户 %s 反思完成", user_id)
        except Exception as e:
            if shared:
                self._release_shared(user_id, lease_token)
            else:
                self._local_leases.discard(user_id)
            logger.error("用户 %s 反思失败: %s", user_id, e, exc_info=True)

    def _complete_shared(self, user_id: str, claimed_count: int, lease_token: str) -> None:
        self._redis.eval(
            _COMPLETE_SCRIPT,
            2,
            self._counter_key(user_id),
            self._lease_key(user_id),
            lease_token,
            claimed_count,
        )

    def _release_shared(self, user_id: str, lease_token: str) -> None:
        try:
            self._redis.eval(_RELEASE_SCRIPT, 1, self._lease_key(user_id), lease_token)
        except redis.RedisError:
            logger.warning("释放用户 %s 的反思租约失败", user_id, exc_info=True)

    def run_memory_maintenance(self):
        """定期记忆维护：衰减过时薄弱点、清理过期记忆"""
        logger.info("开始定期记忆维护...")
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

        logger.info(
            f"记忆维护完成: 处理 {len(user_ids)} 个用户, 删除 {decayed_total} 条过时记忆"
        )

    def start(self):
        if self._started:
            return
        self.scheduler.start()
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
        if not self._started:
            return
        self.scheduler.shutdown(wait=False)
        self._started = False


reflection_scheduler = ReflectionScheduler()
