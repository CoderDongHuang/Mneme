"""Checkpointed completion effects, dispatched by the Gateway's SQL outbox.

Provider calls run outside account transactions. Qdrant writes carry their
effect receipt in the same point mutation; version snapshots preserve that
receipt if a subsequent edit/delete wins before a lost response is replayed.
"""
from copy import deepcopy
from hashlib import sha256
import json

from app.core.config import settings
from app.core.privacy import require_cloud_processing
from app.core.time import parse_utc, utc_now
from app.memory.session_scope import account_session
from app.memory.session_history import session_key
from app.models.chat import MemoryCompletion, Message


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def completion_input(request, state, answer):
    captured = state["memory_input"]
    return MemoryCompletion(user_id=request.user_id, session_id=request.session_id,
                            delivery_id=captured["delivery_id"], reference_time=captured["reference_time"],
                            history=captured["history"], answer=answer.strip()).model_dump()


class Checkpoints:
    def __init__(self, request):
        self.request = request
        self.session_key = session_key(request.session_id)
        self.key = _digest(request.delivery_id)
        self.fingerprint = _digest(request.model_dump())

    def _job(self, state):
        jobs = state.setdefault("memory_completions", {}).setdefault(self.session_key, {})
        job = jobs.setdefault(self.key, {"fingerprint": self.fingerprint, "created_at": utc_now().isoformat(), "phases": {}})
        if (not isinstance(job, dict) or not isinstance(job.get("fingerprint"), str)
                or not isinstance(job.get("phases"), dict) or not isinstance(job.get("created_at"), str)):
            raise ValueError("记忆任务检查点损坏，拒绝执行")
        if job["fingerprint"] != self.fingerprint:
            raise ValueError("记忆任务投递内容冲突")
        # A missing remote acknowledgement must remain distinguishable from a
        # later user deletion. Never replay an unacknowledged effect after its
        # version evidence may have expired.
        if (utc_now() - parse_utc(job["created_at"])).total_seconds() >= max(1, settings.memory_version_retention_days) * 86400:
            unfinished = any(name.startswith("plan:") and "apply:" + name[5:] not in job["phases"] for name in job["phases"])
            if unfinished:
                raise ValueError("记忆任务核验依据已过保留期，拒绝重放写入")
        return job

    def phase(self, name, action):
        with account_session(self.request.user_id, session_id=self.request.session_id) as state:
            job = self._job(state)
            if name in job["phases"]:
                return deepcopy(job["phases"][name])
        result = action()
        with account_session(self.request.user_id, session_id=self.request.session_id) as state:
            # Concurrent workers must all consume the first committed extraction
            # or plan, never apply their own discarded provider result.
            return deepcopy(self._job(state)["phases"].setdefault(name, result))


def _extract(request):
    from app.memory.distillation import distill_conversation

    history = request.history
    if len(history) < 2:
        return []
    try:
        previous = parse_utc(history[-2].timestamp)
    except (ValueError, TypeError):
        return []
    if (parse_utc(request.reference_time) - previous).total_seconds() <= settings.distillation_idle_minutes * 60:
        return []
    return distill_conversation(request.user_id, request.session_id,
                                [{"role": message.role, "content": message.content} for message in history[:-1]])


def _category(store, user_id, category):
    from app.memory.long_term_memory import MAX_PREFERENCES, MAX_WEAK_POINTS

    # The public category projection intentionally omits internal receipts and
    # normalizes metadata. Compare full stored points on both sides of the CAS.
    return [current for item in store.get_by_category(user_id, category, limit=max(MAX_PREFERENCES, MAX_WEAK_POINTS) + 1)
            if (current := store.get_memory(item["id"])) is not None]


def _plan(request, entry, effect):
    from app.memory.long_term_memory import long_term_memory, MAX_PREFERENCES, MAX_WEAK_POINTS

    store = long_term_memory._store
    category, content = entry["category"], entry["content"]
    existing = _category(store, request.user_id, category)
    target = next((item for item in existing if category == "weak_point" and item.get("topic") == entry["topic"]), None)
    if category != "progress" and target is None and long_term_memory._is_duplicate(request.user_id, category, content):
        return {"skip": True}
    now = utc_now().isoformat()
    metadata = {"user_id": request.user_id, "category": category, "topic": entry.get("topic", ""),
                "importance": 0.5, "created_at": now, "updated_at": now,
                "source_session_id": request.session_id, "evidence_hashes": json.dumps(entry.get("evidence_hashes", [])),
                "completion_effect": effect, "completion_reference_time": request.reference_time}
    evict = []
    if target:
        metadata = {key: value for key, value in target.items() if key not in {"id", "content"}}
        metadata.update(importance=min(1.0, target.get("importance", 0.5) + 0.1), updated_at=now, completion_effect=effect)
        content = target["content"]
    elif category == "progress":
        if any(parse_utc(item.get("completion_reference_time") or item["updated_at"]) > parse_utc(request.reference_time)
               for item in existing):
            return {"skip": True}
        parts = content.split("/")
        topic = parts[0] + "/" + (parts[1] if len(parts) > 1 else "")
        metadata["topic"] = topic
        content = "学习进度: " + topic
        evict = existing
    else:
        limit = MAX_PREFERENCES if category == "preference" else MAX_WEAK_POINTS
        if len(existing) >= limit:
            evict = [min(existing, key=lambda item: item.get("importance", 0.5))]
    return {"id": target["id"] if target else "mem_completion_" + effect,
            "before": _digest(target) if target else None, "content": content, "metadata": metadata,
            "category_before": _digest(sorted(existing, key=lambda item: item["id"])),
            "evict": [{"id": item["id"], "before": _digest(item)} for item in evict]}


def _receipt(user_id, memory_id, current, effect):
    if current and current.get("completion_effect") == effect:
        return True
    from app.memory.version_store import memory_version_store

    return any(version["metadata"].get("completion_effect") == effect
               for version in memory_version_store.list_versions(user_id, memory_id))


def _apply(request, plan, effect):
    if plan.get("skip"):
        return "duplicate"
    from app.memory.long_term_memory import long_term_memory
    from app.memory.version_store import memory_version_store
    from app.utils.embedding import embeddings

    require_cloud_processing(request.user_id)
    store = long_term_memory._store
    store._require_embedding_profile()
    # A retry may need no write, but an embedding call never holds the SQL lock.
    vectors = embeddings([plan["content"]])
    with account_session(request.user_id, session_id=request.session_id):
        current = store.get_memory(plan["id"])
        applied = _receipt(request.user_id, plan["id"], current, effect)
        if not applied:
            existing = _category(store, request.user_id, plan["metadata"]["category"])
            if _digest(sorted(existing, key=lambda item: item["id"])) != plan["category_before"]:
                return "superseded"
            if (_digest(current) if current else None) != plan["before"]:
                # The user changed this target after planning. Preserve that
                # newer intent rather than overwrite it on a delayed retry.
                return "superseded"
            if current:
                memory_version_store._snapshot_locked(current, "distillation")
            store._require_embedding_profile()
            store._collection.upsert(ids=[plan["id"]], documents=[plan["content"]],
                                     embeddings=vectors, metadatas=[plan["metadata"]])
        for old in plan["evict"]:
            current_old = store.get_memory(old["id"])
            if current_old and _digest(current_old) == old["before"]:
                memory_version_store._snapshot_locked(current_old, "distillation_replace")
                store._collection.delete(ids=[old["id"]])
    long_term_memory._invalidate_cache(request.user_id)
    return "applied"


def complete_memory(request: MemoryCompletion):
    from app.memory.distillation import apply_distilled_entries, HIGH_CONFIDENCE_THRESHOLD
    from app.memory.reflection_scheduler import reflection_scheduler
    from app.memory.session_store import session_store
    from app.memory.short_term_memory import short_term_memory
    from app.memory.working_memory import working_memory

    require_cloud_processing(request.user_id)
    checkpoints = Checkpoints(request)

    def history():
        assistant = Message(role="assistant", content=request.answer, timestamp=request.reference_time,
                            token_count=max(1, len(request.answer) // 4))
        committed = short_term_memory.add_message(request.session_id, assistant, user_id=request.user_id,
                                                  delivery_id=request.delivery_id)
        working_memory.replace_messages(request.session_id, committed, user_id=request.user_id)
        session_store.increment_message_count(request.user_id, request.session_id, delivery_id=request.delivery_id)
        return True

    checkpoints.phase("history", history)
    entries = checkpoints.phase("extraction", lambda: _extract(request))
    scope = [request.user_id, request.session_id, request.delivery_id]
    for entry in entries:
        if entry["confidence"] < HIGH_CONFIDENCE_THRESHOLD:
            continue
        effect = _digest([scope, entry])
        plan = checkpoints.phase("plan:" + effect, lambda: _plan(request, entry, effect))
        checkpoints.phase("apply:" + effect, lambda: _apply(request, plan, effect))
    pending = apply_distilled_entries(request.user_id,
                                      [entry for entry in entries if entry["confidence"] < HIGH_CONFIDENCE_THRESHOLD],
                                      candidate_scope=scope)

    def reflection():
        reflection_scheduler.record_session(request.user_id, request.session_id, request.delivery_id)
        reflection_scheduler.check_and_trigger(request.user_id)
        return True

    checkpoints.phase("reflection", reflection)

    def summarize():
        if short_term_memory.should_summarize(request.session_id, user_id=request.user_id):
            short_term_memory.summarize(request.session_id, user_id=request.user_id, raise_on_error=True)
        return True

    checkpoints.phase("summary", summarize)
    return {"completed": True, "delivery_id": request.delivery_id, "pending_memories": pending}
