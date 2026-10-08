from concurrent.futures import ThreadPoolExecutor
import uuid
import socket
import time

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.memory.reflection import run_reflection
from app.memory.long_term_memory import long_term_memory
from app.memory.memory_store import memory_store
from app.core.logging import setup_logger
from app.core.config import settings
from app.core.metrics import (
    REFLECTION_LEASE_ACQUISITIONS,
    REFLECTION_LEASE_CONTENTIONS,
    REFLECTION_LEASE_TAKEOVERS,
)

logger = setup_logger("reflection_scheduler")

MEMORY_MAINTENANCE_INTERVAL_HOURS = 24

# 异步执行反思，不阻塞聊天请求线程
_reflection_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="reflection"
)

_COUNTER_PREFIX = "mneme:reflection:sessions:"
_LEASE_PREFIX = "mneme:reflection:lease:"
_LEASE_STATE_PREFIX = "mneme:reflection:lease-state:"
_QUEUE_KEY = "mneme:reflection:queue"
_QUEUE_GROUP = "mneme-reflection-workers"
_QUEUE_CONSUMER_PREFIX = "worker-"
_QUEUE_BLOCK_MS = 1000
_QUEUE_SOCKET_TIMEOUT_SECONDS = 2
_ACQUIRE_SCRIPT = """
if redis.call('exists', KEYS[1]) == 1 then return 0 end
local previous = redis.call('get', KEYS[2]) or ''
redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('set', KEYS[2], 'active')
if previous == 'active' then return 2 else return 1 end
"""
_COMPLETE_SCRIPT = """
if redis.call('get', KEYS[2]) ~= ARGV[1] then return 0 end
local current = tonumber(redis.call('get', KEYS[1]) or '0')
local claimed = tonumber(ARGV[2])
local remaining = current - claimed
if remaining > 0 then redis.call('set', KEYS[1], remaining) else redis.call('del', KEYS[1]) end
redis.call('del', KEYS[2])
redis.call('set', KEYS[3], 'completed')
return 1
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  redis.call('del', KEYS[1])
  redis.call('set', KEYS[2], 'released')
  return 1
else
  return 0
end
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
            socket_timeout=_QUEUE_SOCKET_TIMEOUT_SECONDS,
            decode_responses=True,
        )
        self._redis_available = redis_client is not None
        self._executor = executor or _reflection_executor
        self._started = False
        self._consumer = f"{_QUEUE_CONSUMER_PREFIX}{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._queue_thread = None
        self._queue_stop = None

    def _counter_key(self, user_id: str) -> str:
        return f"{_COUNTER_PREFIX}{user_id}"

    def _lease_key(self, user_id: str) -> str:
        return f"{_LEASE_PREFIX}{user_id}"

    def _lease_state_key(self, user_id: str) -> str:
        return f"{_LEASE_STATE_PREFIX}{user_id}"

    def _ensure_queue(self) -> None:
        try:
            self._redis.xgroup_create(_QUEUE_KEY, _QUEUE_GROUP, id="0", mkstream=True)
        except redis.ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def _enqueue_reflection(self, user_id: str, count: int) -> str:
        self._ensure_queue()
        entry = self._redis.xadd(
            _QUEUE_KEY,
            {"user_id": user_id, "claimed_count": str(count), "queued_at": str(time.time())},
        )
        return entry.decode() if isinstance(entry, bytes) else str(entry)

    def _acquire_shared_lease(self, user_id: str, token: str) -> bool:
        result = int(
            self._redis.eval(
                _ACQUIRE_SCRIPT,
                2,
                self._lease_key(user_id),
                self._lease_state_key(user_id),
                token,
                max(60, settings.memory_reflection_lease_seconds),
            )
        )
        if result == 0:
            REFLECTION_LEASE_CONTENTIONS.inc()
            return False
        REFLECTION_LEASE_ACQUISITIONS.labels("redis").inc()
        if result == 2:
            REFLECTION_LEASE_TAKEOVERS.inc()
        return True

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
            if not self._acquire_shared_lease(user_id, lease_token):
                return False
            shared = True
        except redis.RedisError:
            self._redis_available = False
            count = self._session_counts.get(user_id, 0)
            if count < threshold or user_id in self._local_leases:
                return False
            lease_token = "local"
            self._local_leases.add(user_id)
            REFLECTION_LEASE_ACQUISITIONS.labels("local").inc()
            shared = False
        logger.info("触发用户 %s 的记忆反思（可靠队列）", user_id)
        try:
            self._enqueue_reflection(user_id, count)
        except redis.RedisError:
            self._release_shared(user_id, lease_token) if shared else self._local_leases.discard(user_id)
            raise
        return True

    def _consume_reflections(self) -> None:
        while self._queue_stop is not None and not self._queue_stop.is_set():
            try:
                self._ensure_queue()
                messages = self._redis.xreadgroup(
                    _QUEUE_GROUP, self._consumer, {_QUEUE_KEY: ">"}, count=1, block=_QUEUE_BLOCK_MS
                )
                for _, entries in messages:
                    for message_id, values in entries:
                        self._run_queued_reflection(message_id, values)
            except redis.RedisError:
                logger.warning("反思队列消费失败，将在稍后重试", exc_info=True)
                time.sleep(1)

    def _run_queued_reflection(self, message_id, values) -> None:
        def value(name: str) -> str:
            item = values.get(name) or values.get(name.encode())
            return item.decode() if isinstance(item, bytes) else str(item)

        user_id = value("user_id")
        claimed_count = int(value("claimed_count"))
        lease_token = self._redis.get(self._lease_key(user_id))
        if isinstance(lease_token, bytes):
            lease_token = lease_token.decode()
        if not lease_token:
            lease_token = uuid.uuid4().hex
            if not self._acquire_shared_lease(user_id, lease_token):
                logger.info("用户 %s 反思任务等待租约，保留 pending", user_id)
                return
        if self._run_reflection_safe(user_id, claimed_count, lease_token, True):
            self._redis.xack(_QUEUE_KEY, _QUEUE_GROUP, message_id)

    def reclaim_stale_reflections(self, min_idle_ms: int | None = None) -> int:
        """Reclaim pending jobs after a crashed worker, preserving at-least-once delivery."""
        self._ensure_queue()
        idle = min_idle_ms or max(1000, settings.memory_reflection_lease_seconds * 1000)
        reclaimed = self._redis.xautoclaim(
            _QUEUE_KEY, _QUEUE_GROUP, self._consumer, idle, start_id="0-0", count=20
        )
        entries = reclaimed[1] if len(reclaimed) > 1 else []
        for message_id, values in entries:
            self._run_queued_reflection(message_id, values)
        return len(entries)

    def _run_reflection_safe(
        self, user_id: str, claimed_count: int = 0, lease_token: str = "", shared: bool = False
    ) -> bool:
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
            return True
        except Exception as e:
            if not shared:
                self._local_leases.discard(user_id)
            # A queued task keeps its lease until expiry. This prevents a new
            # trigger from creating a duplicate while the pending entry waits
            # for XAUTOCLAIM to retry it.
            logger.error("用户 %s 反思失败: %s", user_id, e, exc_info=True)
            return False

    def _complete_shared(self, user_id: str, claimed_count: int, lease_token: str) -> None:
        self._redis.eval(
            _COMPLETE_SCRIPT,
            3,
            self._counter_key(user_id),
            self._lease_key(user_id),
            self._lease_state_key(user_id),
            lease_token,
            claimed_count,
        )

    def _release_shared(self, user_id: str, lease_token: str) -> None:
        try:
            self._redis.eval(
                _RELEASE_SCRIPT,
                2,
                self._lease_key(user_id),
                self._lease_state_key(user_id),
                lease_token,
            )
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
        from app.agents.trace_store import agent_trace_store
        self.scheduler.add_job(agent_trace_store.prune_policies, trigger=IntervalTrigger(hours=1),
                               id="privacy_retention", replace_existing=True)
        self.scheduler.add_job(
            self.run_memory_maintenance,
            trigger=IntervalTrigger(hours=MEMORY_MAINTENANCE_INTERVAL_HOURS),
            id="memory_maintenance",
            name="记忆衰减与过期清理",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.reclaim_stale_reflections,
            trigger=IntervalTrigger(seconds=max(30, settings.memory_reflection_lease_seconds // 2)),
            id="reflection_queue_reclaim",
            name="接管超时反思任务",
            replace_existing=True,
        )
        import threading
        self._queue_stop = threading.Event()
        self._queue_thread = threading.Thread(
            target=self._consume_reflections, name="reflection-queue", daemon=True
        )
        self._queue_thread.start()
        logger.info(
            f"记忆反思调度器已启动 (维护间隔: {MEMORY_MAINTENANCE_INTERVAL_HOURS}h)"
        )
        self._started = True

    def shutdown(self):
        if not self._started:
            return
        self.scheduler.shutdown(wait=False)
        if self._queue_stop is not None:
            self._queue_stop.set()
        if self._queue_thread is not None:
            self._queue_thread.join(timeout=2)
        self._queue_thread = None
        self._queue_stop = None
        self._started = False


reflection_scheduler = ReflectionScheduler()
