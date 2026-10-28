"""Cooperative, cross-process cancellation for the durable gateway task queue."""
from contextvars import ContextVar
from contextlib import contextmanager
import threading
import uuid
import redis
from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("ingestion_cancellation")


class IngestionCancelled(RuntimeError):
    pass


class IngestionLeaseLost(RuntimeError):
    pass


_task = ContextVar("ingestion_task", default=None)
_LEASE_SECONDS = 60
_LEASE_RENEW_SECONDS = 20
_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def check_cancelled():
    task = _task.get()
    if task is None:
        return
    user_id, task_id, lease_lost, owner = task
    if lease_lost.is_set():
        raise IngestionLeaseLost("解析任务租约已丢失，已停止处理以避免并发写入")
    client = redis.Redis(host=settings.redis_host, port=settings.redis_port, db=settings.redis_db,
                         password=settings.redis_password or None, socket_timeout=3, socket_connect_timeout=3)
    try:
        # A suspended process may resume before its heartbeat thread runs. Check
        # ownership synchronously at every checkpoint, failing closed on Redis errors.
        try:
            valid = _renew_lease(client, f"mneme:ingestion:active:{user_id}:{task_id}", owner)
        except redis.RedisError as error:
            lease_lost.set()
            raise IngestionLeaseLost("无法确认解析任务租约，已停止处理") from error
        if not valid:
            lease_lost.set()
            raise IngestionLeaseLost("解析任务租约已丢失，已停止处理")
        if client.exists(f"mneme:ingestion:cancel:{user_id}:{task_id}"):
            raise IngestionCancelled("解析任务已取消")
    finally:
        client.close()


def _renew_lease(client, key, owner):
    return bool(client.eval(_RENEW_SCRIPT, 1, key, owner, _LEASE_SECONDS))


def _release_lease(client, key, owner):
    return bool(client.eval(_RELEASE_SCRIPT, 1, key, owner))


def _heartbeat(client, key, owner, stop, lease_lost):
    while not stop.wait(_LEASE_RENEW_SECONDS):
        try:
            if not _renew_lease(client, key, owner):
                lease_lost.set()
                return
        except Exception:
            lease_lost.set()
            return


@contextmanager
def ingestion_task(user_id, task_id):
    lease_lost = threading.Event()
    client = None
    acquired = False
    key = f"mneme:ingestion:active:{user_id}:{task_id}"
    owner = uuid.uuid4().hex
    token = _task.set((user_id, task_id, lease_lost, owner) if task_id else None)
    stop = threading.Event()
    heartbeat = None
    try:
        if task_id:
            client = redis.Redis(host=settings.redis_host, port=settings.redis_port, db=settings.redis_db,
                                 password=settings.redis_password or None, socket_timeout=3, socket_connect_timeout=3)
            if not client.set(key, owner, nx=True, ex=_LEASE_SECONDS):
                raise RuntimeError("同一解析任务仍在运行，请等待其结束后重试")
            acquired = True
            heartbeat = threading.Thread(
                target=_heartbeat,
                args=(client, key, owner, stop, lease_lost),
                name=f"ingestion-lease-{task_id}",
                daemon=True,
            )
            heartbeat.start()
        check_cancelled()
        yield
    finally:
        _task.reset(token)
        if client:
            stop.set()
            if heartbeat:
                heartbeat.join(timeout=4)
            try:
                if acquired:
                    _release_lease(client, key, owner)
            except redis.RedisError:
                # The short TTL is the fallback. Cleanup must not hide a body error.
                logger.warning("解析任务租约释放失败，等待租约到期: task=%s", task_id)
            finally:
                client.close()
