"""Bound SQL checkpoints without discarding the evidence needed for replay.

A single monotonic account cutoff replaces expired receipts. Requests at or
before it cannot execute, even after a clock rollback or a policy extension.
Legacy checkpoints without a captured reference instant remain protected.
"""
import json
from datetime import timedelta

from app.core.config import settings
from app.core.time import parse_utc, utc_now


def _instant(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        return parse_utc(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("记忆任务留存时间损坏") from None


def _cutoff(state):
    days = min(settings.memory_completion_retention_days, max(1, settings.memory_version_retention_days))
    cutoff = utc_now() - timedelta(days=days)
    if "memory_completion_retired_before" in state:
        cutoff = max(cutoff, _instant(state["memory_completion_retired_before"]))
    return cutoff


def _jobs(state):
    jobs = state.get("memory_completions", {})
    if not isinstance(jobs, dict):
        raise ValueError("记忆任务检查点损坏，拒绝执行")
    for session, entries in jobs.items():
        if not isinstance(session, str) or not isinstance(entries, dict):
            raise ValueError("记忆任务检查点损坏，拒绝执行")
        for key, job in entries.items():
            if (not isinstance(key, str) or not isinstance(job, dict)
                    or not isinstance(job.get("fingerprint"), str) or not isinstance(job.get("phases"), dict)):
                raise ValueError("记忆任务检查点损坏，拒绝执行")
            _instant(job.get("created_at"))
            if "reference_time" in job:
                _instant(job["reference_time"])
    return jobs


def expire_user(state):
    jobs = _jobs(state)
    cutoff = _cutoff(state)
    expired = [(session, key) for session, entries in jobs.items() for key, job in entries.items()
               if "reference_time" in job and _instant(job["reference_time"]) <= cutoff]
    # Validate the complete inventory before deleting anything. Unknown legacy
    # timestamps cannot be inferred from created_at and are never guessed.
    for session, key in expired:
        del jobs[session][key]
    for session in list(jobs):
        if not jobs[session]:
            del jobs[session]
    if expired:
        state["memory_completion_retired_before"] = cutoff.isoformat()
    return len(expired)


def require_current(state, reference_time):
    instant = _instant(reference_time)
    if instant <= _cutoff(state):
        raise ValueError("记忆任务已过保留期，拒绝重放写入")
    if instant > utc_now() + timedelta(minutes=5):
        raise ValueError("记忆任务时间超出允许范围")


def require_capacity(state):
    jobs = _jobs(state)
    count = sum(len(entries) for entries in jobs.values())
    size = len(json.dumps(jobs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    if count > settings.memory_completion_max_jobs or size > settings.memory_completion_max_bytes:
        raise ValueError("记忆任务检查点容量已满，请等待留存回收或删除不再需要的会话")
