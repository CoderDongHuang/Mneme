"""
异步任务状态追踪

文档上传后返回 task_id，前端轮询 GET /api/v1/knowledge/task/{task_id} 查询进度。

任务状态流转：processing → done | failed
"""

import uuid
import threading
from typing import Dict, Optional

from app.core.time import utc_now, parse_utc
from app.core.config import settings

# 内存存储（生产环境应迁移到 Redis）
_task_store: Dict[str, dict] = {}
_lock = threading.Lock()

# 仅对终态历史计时；运行任务不能因耗时超过留存窗口而消失。
TASK_TTL_SECONDS = settings.ingestion_task_retention_seconds


def _prune_completed(now) -> None:
    expired = [
        task_id for task_id, info in _task_store.items()
        if info.get("status") in {"done", "failed"}
        and (now - parse_utc(info.get("completed_at") or info["created_at"])).total_seconds() > TASK_TTL_SECONDS
    ]
    for task_id in expired:
        del _task_store[task_id]


def create_task() -> str:
    """创建任务记录，返回 task_id"""
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    with _lock:
        now = utc_now()
        _prune_completed(now)
        _task_store[task_id] = {
            "status": "processing",
            "chunks": 0,
            "error": None,
            "created_at": now.isoformat(),
        }
    return task_id


def update_task(
    task_id: str,
    status: str,
    chunks: int = 0,
    error: str | None = None,
    document_id: str | None = None,
):
    """更新任务状态"""
    with _lock:
        now = utc_now()
        _prune_completed(now)
        if task_id in _task_store:
            _task_store[task_id]["status"] = status
            if status in {"done", "failed"}:
                _task_store[task_id].setdefault("completed_at", now.isoformat())
            if chunks:
                _task_store[task_id]["chunks"] = chunks
            if error:
                _task_store[task_id]["error"] = error
            if document_id:
                _task_store[task_id]["document_id"] = document_id


def get_task(task_id: str) -> Optional[dict]:
    """查询任务状态"""
    with _lock:
        _prune_completed(utc_now())
        task = _task_store.get(task_id)
        return dict(task) if task is not None else None
