"""Scoped real-stack provider/candidate fixture, installed and restored by E2E only."""
import contextvars as _qa_contextvars
import json as _qa_json
from datetime import timedelta as _QaDelta
from langchain_core.messages import AIMessageChunk as _QaChunk
from langchain_core.messages import AIMessage as _QaMessage
from app.core.time import utc_now as _qa_now
from app.memory.short_term_memory import short_term_memory as _qa_short
from app.models.chat import Message as _QaHistoryMessage
from app.memory import distillation as _qa_distillation
from app.agents.nodes import memory_write_node as _qa_memory_write
from app.memory.reflection_scheduler import reflection_scheduler as _qa_reflection
from app.agents.trace_store import agent_trace_store as _qa_trace
from app.memory.short_term_memory import ShortTermMemoryManager as _QaShortManager
from unittest.mock import patch as _qa_patch, Mock as _QaMock
import app.agents.nodes as _qa_nodes
import app.memory.short_term_memory as _qa_stm
import app.memory.reflection as _qa_reflection_module
import app.memory.session_persistence as _qa_persistence
from app.memory.session_scope import account_session as _qa_account, cache_key as _qa_key, session_revision as _qa_revision
import traceback as _qa_traceback
import time as _qa_time

_qa_context = _qa_contextvars.ContextVar("memory_outbox_probe", default=False)
_qa_prepare = prepare_conversation  # noqa: F821 -- injected module globals
_qa_complete = complete_conversation  # noqa: F821
_qa_llm = llm  # noqa: F821
_qa_distill_llm = _qa_distillation.llm
_qa_seeded = set()


def prepare_conversation(request):
    scope = _qa_json.loads((_qa_root / "scope.json").read_text(encoding="utf-8"))  # noqa: F821
    matches = str(request.user_id) == scope["user"] and str(request.session_id) == scope["session"]
    _qa_context.set(matches)
    if matches and request.session_id not in _qa_seeded:
        _qa_seeded.add(request.session_id)
        for role, content in [("user", "Historical snapshot preference"), ("assistant", "Prior snapshot answer")]:
            _qa_short.add_message(request.session_id, _QaHistoryMessage(
                role=role, content=content, timestamp=(_qa_now() - _QaDelta(minutes=20)).isoformat(), token_count=5), user_id=request.user_id)
    state = _qa_prepare(request)
    if matches:
        state["intent"] = "general"
    return state


def complete_conversation(request, state, answer):
    if not _qa_context.get():
        return _qa_complete(request, state, answer)
    scope = _qa_json.loads((_qa_root / "scope.json").read_text(encoding="utf-8"))  # noqa: F821
    canary = scope["privacy_canary"]
    # Exercise actual persistence error handlers, without interrupting the
    # service's real Redis client or storing private canaries in Redis.
    for stage in ("connect", "save", "load", "malformed", "delete", "count"):
        probe_session = "privacy-fault-" + stage
        backend = _QaMock()
        if stage == "malformed":
            backend.get.return_value = _qa_json.dumps([{"role": "user", "content": {"private": canary}}])
        else:
            operation = {"connect": "ping", "save": "setex", "load": "get", "delete": "delete", "count": "exists"}[stage]
            getattr(backend, operation).side_effect = RuntimeError(canary)
        with _qa_patch.object(_qa_persistence.redis, "Redis", return_value=backend):
            if stage == "connect":
                persistence = _qa_persistence.SessionPersistence()
            else:
                persistence = object.__new__(_qa_persistence.SessionPersistence)
                persistence._redis, persistence._available = backend, True
                persistence._last_attempt = _qa_time.monotonic()
                if stage == "save":
                    persistence.save_messages(probe_session, [_QaHistoryMessage(
                        role="user", content=canary, timestamp=_qa_now().isoformat())], user_id=request.user_id)
                elif stage in {"load", "malformed"}:
                    assert persistence.load_messages(probe_session, user_id=request.user_id) is None
                else:
                    try:
                        if stage == "delete":
                            persistence.delete_session(probe_session, user_id=request.user_id)
                        else:
                            persistence.count_sessions([probe_session], user_id=request.user_id)
                    except RuntimeError as error:
                        assert error.__suppress_context__ and error.__cause__ is None
                        assert canary not in "".join(_qa_traceback.format_exception(error))
                        _qa_persistence.logger.exception("QA session cleanup failed; retry required")
                    else:
                        raise AssertionError("Session cleanup must fail, never claim erasure")
            assert not persistence.available
    # Provider exceptions can echo private prompts. Exercise the actual fallback
    # paths inside this account's HTTP request; only provider failures are injected.
    with _qa_patch.object(_qa_nodes, "llm", _QaMock(invoke=_QaMock(side_effect=RuntimeError(canary)))):
        assert _qa_nodes.intent_classification_node({**state, "message": canary}) == {"intent": "qa", "confidence": 0.5}
    with _qa_patch.object(_qa_nodes, "run_reflection", side_effect=RuntimeError(canary)):
        assert _qa_nodes.suggestion_generation_node(state) == {}
    # Invalid provider JSON must raise in the actual parser, while on-demand
    # suggestions can still use their existing safe fallback.
    with (_qa_patch.object(_qa_reflection_module.long_term_memory, "get_preferences", return_value=[{"content": "QA"}]),
          _qa_patch.object(_qa_reflection_module.long_term_memory, "get_weak_points", return_value=[]),
          _qa_patch.object(_qa_reflection_module.long_term_memory, "get_progress", return_value=None),
          _qa_patch.object(_qa_reflection_module, "llm", _QaMock(invoke=_QaMock(return_value=_QaMessage(content=canary))))):
        try:
            _qa_reflection_module.run_reflection(request.user_id)
        except _qa_reflection_module.ReflectionResultError as error:
            assert canary not in str(error) and error.__context__ is None
        else:
            raise AssertionError("Invalid reflection must fail")
        assert _qa_nodes.suggestion_generation_node(state) == {}
    temporary = _QaShortManager()
    temporary_key = _qa_key(request.user_id, request.session_id)
    temporary._store[temporary_key] = [_QaHistoryMessage(
        role="user", content=canary, timestamp=_qa_now().isoformat(), token_count=500) for _ in range(30)]
    with _qa_account(request.user_id) as account:
        temporary._revisions[temporary_key] = _qa_revision(account, request.session_id)
    original_history = temporary._store[temporary_key].copy()
    with _qa_patch.object(_qa_stm, "llm", _QaMock(invoke=_QaMock(side_effect=RuntimeError(canary)))):
        temporary.summarize(request.session_id, user_id=request.user_id)
        _qa_stm.llm.invoke.assert_called_once()
    assert temporary._store[temporary_key] == original_history
    try:
        with _qa_trace.span(request.user_id, request.session_id, "privacy.provider_failure", {"content": canary}):
            raise RuntimeError(canary)
    except RuntimeError:
        pass
    rows = _qa_trace.list_session(request.user_id, request.session_id)
    assert any(row["node"] == "privacy.provider_failure" and row["status"] == "error" for row in rows)
    assert canary not in _qa_json.dumps(rows)
    (_qa_root / "privacy-check.json").write_text(_qa_json.dumps({  # noqa: F821
        "intent_fallback": True, "suggestion_fallback": True, "summary_history_preserved": True,
        "real_trace_redacted": True,
        "redis_session_diagnostics_redacted": True,
    }))
    # Run the actual completion and distillation pipeline. Only provider output
    # is controlled: cache reads, idle detection, IDs and Redis writes are real.
    result = _qa_complete(request, state, answer)
    repeated = _qa_memory_write(state)
    assert result["pending_memories"] == repeated["pending_memories"]
    assert len(state["memory_input"]["history"]) == 3
    assert any(m.content == "Later turn must not be distilled" for m in _qa_short.get_history(request.session_id, user_id=request.user_id))
    marker = _qa_reflection._delivery_key(request.user_id, request.session_id, state["memory_input"]["delivery_id"])
    assert _qa_reflection._redis.exists(marker) == 1
    assert _qa_reflection._redis.ttl(marker) > 0
    (_qa_root / "snapshot-check.json").write_text(_qa_json.dumps({  # noqa: F821
        "snapshot_frozen": True, "candidate_stable": True, "actual_completion": True,
        "reflection_delivery_recorded": True,
    }))
    return result


class _QaDistiller:
    def __getattr__(self, name):
        return getattr(_qa_distill_llm, name)

    def invoke(self, messages, **kwargs):
        if not _qa_context.get():
            return _qa_distill_llm.invoke(messages, **kwargs)
        text = "\n".join(str(message.content) for message in messages)
        assert "Historical snapshot preference" in text
        assert "Later turn must not be distilled" not in text
        assert "Candidate memory QA verified answer" not in text
        return _QaMessage(content=_qa_json.dumps([{
            "category": "preference", "content": "Candidate memory QA preference",
            "topic": "Memory outbox QA", "confidence": 0.7, "is_new": True,
        }]))


class _QaProvider:
    def __getattr__(self, name):
        return getattr(_qa_llm, name)

    def astream(self, messages, **kwargs):
        if not _qa_context.get():
            return _qa_llm.astream(messages, **kwargs)

        async def controlled():
            scope = _qa_json.loads((_qa_root / "scope.json").read_text())  # noqa: F821
            _qa_short.add_message(scope["session"], _QaHistoryMessage(
                role="user", content="Later turn must not be distilled", timestamp=_qa_now().isoformat(), token_count=8), user_id=scope["user"])
            yield _QaChunk(content="Candidate memory QA verified answer")
        return controlled()


llm = _QaProvider()
_qa_distillation.llm = _QaDistiller()
