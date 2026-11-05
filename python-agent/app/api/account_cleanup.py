"""Read-only, fail-closed account cleanup evidence; never use filtered UI lists."""
from app.agents.trace_store import agent_trace_store
from app.core.privacy import privacy_store
from app.knowledge.generations import generation_store
from app.knowledge.vector_store import vector_store
from app.memory.memory_store import memory_store
from app.memory.version_store import memory_version_store
from app.memory.reflection_scheduler import reflection_scheduler
from app.memory.session_store import session_store
from app.memory.session_persistence import session_persistence
from app.memory import session_history
from app.tools.registry import tool_registry


def deletion_report(user_id: str) -> dict[str, int]:
    counts = vector_store.deletion_report(user_id)
    counters = {
        "account_fence": lambda: 0 if generation_store.snapshot(user_id).get("deleted") is True else 1,
        "long_term_memories": lambda: memory_store.count_user_memories(user_id),
        "memory_versions": lambda: memory_version_store.count_user(user_id),
        "traces": lambda: agent_trace_store.count_user(user_id),
        "privacy_rows": lambda: privacy_store.count_user(user_id),
        "tool_governance": lambda: tool_registry.count_user_governance(user_id),
        "session_manifest": lambda: len(session_store.cleanup_session_ids(user_id)),
        "sql_session_histories": lambda: session_history.count_user(user_id),
        "redis_scoped_sessions": lambda: session_persistence.count_user_sessions(user_id),
        "reflection_keys": lambda: reflection_scheduler.count_user_keys(user_id),
        "reflection_queue_entries": lambda: reflection_scheduler.count_user_queue(user_id),
    }
    for name, counter in counters.items():
        try:
            value = counter()
            counts[name] = value if type(value) is int and value >= 0 else -1
        except Exception:
            # No exception text, identifiers, content or credentials in evidence.
            counts[name] = -1
    return counts
