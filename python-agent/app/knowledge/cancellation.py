"""Cooperative, cross-process cancellation for the durable gateway task queue."""
from contextvars import ContextVar
from contextlib import contextmanager
import redis
from app.core.config import settings


class IngestionCancelled(RuntimeError):
    pass


_task = ContextVar("ingestion_task", default=None)


def check_cancelled():
    task = _task.get()
    if task is None:
        return
    user_id, task_id = task
    client = redis.Redis(host=settings.redis_host, port=settings.redis_port, db=settings.redis_db,
                         password=settings.redis_password or None, socket_timeout=3, socket_connect_timeout=3)
    try:
        if client.exists(f"mneme:ingestion:cancel:{user_id}:{task_id}"):
            raise IngestionCancelled("解析任务已取消")
    finally:
        client.close()


@contextmanager
def ingestion_task(user_id, task_id):
    token = _task.set((user_id, task_id) if task_id else None)
    client = None
    acquired = False
    key = f"mneme:ingestion:active:{user_id}:{task_id}"
    try:
        if task_id:
            client = redis.Redis(host=settings.redis_host, port=settings.redis_port, db=settings.redis_db,
                                 password=settings.redis_password or None, socket_timeout=3, socket_connect_timeout=3)
            if not client.set(key, "1", nx=True, ex=43200):
                raise RuntimeError("同一解析任务仍在运行，请等待其结束后重试")
            acquired = True
        check_cancelled()
        yield
    finally:
        _task.reset(token)
        if client:
            if acquired:
                client.delete(key)
            client.close()
