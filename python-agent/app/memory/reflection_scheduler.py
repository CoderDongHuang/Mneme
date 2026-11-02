import threading
import uuid
import socket
import time

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.memory.reflection import run_reflection
from app.memory.long_term_memory import long_term_memory
from app.memory.memory_store import memory_store
from app.core.logging import setup_logger, memory_log_fields
from app.core.config import settings
from app.core.metrics import (
    REFLECTION_LEASE_ACQUISITIONS,
    REFLECTION_LEASE_CONTENTIONS,
    REFLECTION_LEASE_TAKEOVERS,
)

logger = setup_logger("reflection_scheduler")

MEMORY_MAINTENANCE_INTERVAL_HOURS = 24

_COUNTER_PREFIX = "mneme:reflection:sessions:"
_LEASE_PREFIX = "mneme:reflection:lease:"
_LEASE_STATE_PREFIX = "mneme:reflection:lease-state:"
_JOB_PREFIX = "mneme:reflection:job:"
_QUEUE_KEY = "mneme:reflection:queue"
_QUEUE_GROUP = "mneme-reflection-workers"
_QUEUE_CONSUMER_PREFIX = "worker-"
_QUEUE_BLOCK_MS = 1000
_QUEUE_SOCKET_TIMEOUT_SECONDS = 2
_MIGRATE_SCRIPT = """
if redis.call('exists', KEYS[2]) == 1 then return 0 end
if #redis.call('xrange', KEYS[4], ARGV[2], ARGV[2]) == 0 then return 0 end
if redis.call('exists', KEYS[1]) == 0 then
  local count = tonumber(redis.call('get', KEYS[3]) or '0')
  if count > 0 then
    redis.call('xadd', KEYS[4], '*', 'user_id', ARGV[3], 'claimed_count', count,
      'queued_at', ARGV[4], 'job_token', ARGV[5])
    redis.call('set', KEYS[1], ARGV[5])
  end
end
redis.call('xack', KEYS[4], ARGV[1], ARGV[2])
redis.call('xdel', KEYS[4], ARGV[2])
return 1
"""
_ENQUEUE_SCRIPT = """
if redis.call('exists', KEYS[1]) == 1 or redis.call('exists', KEYS[2]) == 1 then return 0 end
local count = tonumber(redis.call('get', KEYS[3]) or '0')
if count < tonumber(ARGV[1]) then return 0 end
local entry = redis.call('xadd', KEYS[4], '*', 'user_id', ARGV[2],
  'claimed_count', count, 'queued_at', ARGV[3], 'job_token', ARGV[4])
redis.call('set', KEYS[1], ARGV[4])
return entry
"""
_CLAIM_SCRIPT = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call('exists', KEYS[2]) == 1 then return 0 end
local previous = redis.call('get', KEYS[3]) or ''
redis.call('set', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('set', KEYS[3], 'active', 'EX', 604800)
if previous == 'active' then return 2 else return 1 end
"""
_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) ~= ARGV[1] or redis.call('get', KEYS[2]) ~= ARGV[2] then return 0 end
redis.call('expire', KEYS[2], ARGV[3])
return 1
"""
_COMPLETE_SCRIPT = """
if redis.call('get', KEYS[4]) ~= ARGV[1] or redis.call('get', KEYS[2]) ~= ARGV[2] then return 0 end
local current = tonumber(redis.call('get', KEYS[1]) or '0')
local claimed = tonumber(ARGV[3])
local remaining = current - claimed
if redis.call('xack', KEYS[5], ARGV[4], ARGV[5]) ~= 1 then return 0 end
if remaining > 0 then redis.call('set', KEYS[1], remaining, 'KEEPTTL') else redis.call('del', KEYS[1]) end
redis.call('del', KEYS[2])
redis.call('del', KEYS[4])
redis.call('set', KEYS[3], 'completed', 'EX', 604800)
redis.call('xdel', KEYS[5], ARGV[5])
return 1
"""


class ReflectionScheduler:
    def __init__(self, redis_client=None):
        self.scheduler = BackgroundScheduler()
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
        self._started = False
        self._consumer = f"{_QUEUE_CONSUMER_PREFIX}{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._queue_thread = None
        self._queue_stop = None
        self._reclaim_cursor = "0-0"

    def _counter_key(self, user_id: str) -> str:
        return f"{_COUNTER_PREFIX}{user_id}"

    def _lease_key(self, user_id: str) -> str:
        return f"{_LEASE_PREFIX}{user_id}"

    def _lease_state_key(self, user_id: str) -> str:
        return f"{_LEASE_STATE_PREFIX}{user_id}"

    def _job_key(self, user_id: str) -> str:
        return f"{_JOB_PREFIX}{user_id}"

    def _lease_seconds(self) -> int:
        return max(60, settings.memory_reflection_lease_seconds)

    def _ensure_queue(self) -> None:
        try:
            self._redis.xgroup_create(_QUEUE_KEY, _QUEUE_GROUP, id="0", mkstream=True)
        except redis.ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def _claim_shared(self, user_id: str, job_token: str, owner: str) -> bool:
        result = int(
            self._redis.eval(
                _CLAIM_SCRIPT,
                3,
                self._job_key(user_id),
                self._lease_key(user_id),
                self._lease_state_key(user_id),
                job_token,
                owner,
                self._lease_seconds(),
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
        """Reliable task state must never silently fall back to process memory."""
        try:
            count = int(self._redis.incr(self._counter_key(user_id)))
            if count == 1:
                self._redis.expire(self._counter_key(user_id), 7 * 24 * 60 * 60)
            self._redis_available = True
            return count
        except redis.RedisError:
            self._redis_available = False
            logger.warning("reflection_counter_unavailable operation=record_session")
            raise

    def check_and_trigger(self, user_id: str) -> bool:
        """Persist the job and its per-user reservation in one Redis operation."""
        try:
            self._ensure_queue()
            entry = self._redis.eval(
                _ENQUEUE_SCRIPT, 4, self._job_key(user_id), self._lease_key(user_id),
                self._counter_key(user_id), _QUEUE_KEY,
                settings.memory_reflection_every_sessions, user_id, str(time.time()), uuid.uuid4().hex,
            )
            self._redis_available = True
        except redis.RedisError:
            self._redis_available = False
            logger.warning("reflection_queue_unavailable operation=check_and_trigger")
            raise
        if entry:
            logger.info(memory_log_fields("enqueue_reflection", "queued", user_id=user_id))
        return bool(entry)

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
            return item.decode() if isinstance(item, bytes) else str(item or "")

        user_id = value("user_id")
        claimed_count = int(value("claimed_count"))
        job_token = value("job_token")
        if not job_token:
            # Upgrade only after the old owner lease expires. Read the current
            # aggregate counter, not a possibly duplicated legacy snapshot.
            migrated = self._redis.eval(
                _MIGRATE_SCRIPT, 4, self._job_key(user_id), self._lease_key(user_id),
                self._counter_key(user_id), _QUEUE_KEY, _QUEUE_GROUP, message_id,
                user_id, str(time.time()), uuid.uuid4().hex,
            )
            logger.info(memory_log_fields(
                "reflection_upgrade", "migrated" if migrated else "pending", user_id=user_id
            ))
            return
        owner = uuid.uuid4().hex
        if not self._claim_shared(user_id, job_token, owner):
            logger.info(memory_log_fields("reflection_lease", "pending", user_id=user_id))
            return
        self._run_reflection_safe(user_id, claimed_count, job_token, owner, message_id)

    def reclaim_stale_reflections(self, min_idle_ms: int | None = None) -> int:
        """Reclaim pending jobs after a crashed worker, preserving at-least-once delivery."""
        self._ensure_queue()
        idle = min_idle_ms or self._lease_seconds() * 1000
        reclaimed = self._redis.xautoclaim(
            _QUEUE_KEY, _QUEUE_GROUP, self._consumer, idle, start_id=self._reclaim_cursor, count=20
        )
        self._reclaim_cursor = reclaimed[0]
        entries = reclaimed[1] if len(reclaimed) > 1 else []
        for message_id, values in entries:
            self._run_queued_reflection(message_id, values)
        return len(entries)

    def _run_reflection_safe(
        self, user_id: str, claimed_count: int, job_token: str, owner: str, message_id: str
    ) -> bool:
        """A fresh owner renews only its own job; lost owners cannot commit."""
        stop, lost = threading.Event(), threading.Event()

        def renew():
            while not stop.wait(self._lease_seconds() / 3):
                try:
                    renewed = self._redis.eval(
                        _RENEW_SCRIPT, 2, self._job_key(user_id), self._lease_key(user_id),
                        job_token, owner, self._lease_seconds(),
                    )
                    if not renewed:
                        lost.set()
                        return
                except redis.RedisError:
                    lost.set()
                    logger.warning(memory_log_fields("reflection_heartbeat", "unavailable", user_id=user_id))
                    return

        heartbeat = threading.Thread(target=renew, name="reflection-heartbeat", daemon=True)
        heartbeat.start()
        try:
            run_reflection(user_id)
            if lost.is_set() or not self._complete_shared(
                user_id, claimed_count, job_token, owner, message_id
            ):
                logger.warning(memory_log_fields("reflect", "ownership_lost", user_id=user_id))
                return False
            logger.info(memory_log_fields("reflect", "completed", user_id=user_id))
            return True
        except Exception as e:
            # A queued task keeps its lease until expiry. This prevents a new
            # trigger from creating a duplicate while the pending entry waits
            # for XAUTOCLAIM to retry it.
            logger.error("error_type=%s %s", type(e).__name__,
                         memory_log_fields("reflect", "failed", user_id=user_id))
            return False
        finally:
            stop.set()
            heartbeat.join(timeout=_QUEUE_SOCKET_TIMEOUT_SECONDS + 1)

    def _complete_shared(
        self, user_id: str, claimed_count: int, job_token: str, owner: str, message_id: str
    ) -> bool:
        return bool(self._redis.eval(
            _COMPLETE_SCRIPT,
            5,
            self._counter_key(user_id),
            self._lease_key(user_id),
            self._lease_state_key(user_id),
            self._job_key(user_id),
            _QUEUE_KEY,
            job_token,
            owner,
            claimed_count,
            _QUEUE_GROUP,
            message_id,
        ))

    def queue_available(self) -> bool:
        try:
            self._redis_available = bool(self._redis.ping())
        except redis.RedisError:
            self._redis_available = False
        return self._redis_available

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
                    logger.info("removed_count=%d %s", removed,
                                memory_log_fields("maintenance", "completed", user_id=user_id))
            except Exception as e:
                logger.error("error_type=%s %s", type(e).__name__,
                             memory_log_fields("maintenance", "failed", user_id=user_id))

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
