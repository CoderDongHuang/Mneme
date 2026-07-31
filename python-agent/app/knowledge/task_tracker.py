"""
异步任务状态追踪

文档上传后返回 task_id，前端轮询 GET /api/v1/knowledge/task/{task_id} 查询进度。

任务状态流转：processing → done | failed
"""

import uuid
import threading
from datetime import datetime
from typing import Dict, Optional

from app.core.logging import setup_logger

logger = setup_logger("task_tracker")

# 内存存储（生产环境应迁移到 Redis）
_task_store: Dict[str, dict] = {}
_lock = threading.Lock()

# 任务 TTL（秒）：1 小时后自动清理
TASK_TTL_SECONDS = 3600


def create_task() -> str:
    """创建任务记录，返回 task_id"""
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    with _lock:
        _task_store[task_id] = {
            "status": "processing",
            "chunks": 0,
            "error": None,
            "created_at": datetime.now().isoformat(),
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
        if task_id in _task_store:
            _task_store[task_id]["status"] = status
            if chunks:
                _task_store[task_id]["chunks"] = chunks
            if error:
                _task_store[task_id]["error"] = error
            if document_id:
                _task_store[task_id]["document_id"] = document_id


def get_task(task_id: str) -> Optional[dict]:
    """查询任务状态"""
    with _lock:
        # 清理过期任务
        now = datetime.now()
        expired = []
        for tid, info in _task_store.items():
            created = datetime.fromisoformat(info["created_at"])
            if (now - created).total_seconds() > TASK_TTL_SECONDS:
                expired.append(tid)
        for tid in expired:
            del _task_store[tid]

        return _task_store.get(task_id)
