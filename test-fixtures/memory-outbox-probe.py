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

_qa_context = _qa_contextvars.ContextVar("memory_outbox_probe", default=False)
_qa_prepare = prepare_conversation  # noqa: F821 -- injected module globals
_qa_complete = complete_conversation  # noqa: F821
_qa_llm = llm  # noqa: F821
_qa_distill_llm = _qa_distillation.llm
_qa_seeded = set()


def prepare_conversation(request):
    scope = _qa_json.loads((_qa_root / "scope.json").read_text())  # noqa: F821
    matches = str(request.user_id) == scope["user"] and str(request.session_id) == scope["session"]
    _qa_context.set(matches)
    if matches and request.session_id not in _qa_seeded:
        _qa_seeded.add(request.session_id)
        for role, content in [("user", "Historical snapshot preference"), ("assistant", "Prior snapshot answer")]:
            _qa_short.add_message(request.session_id, _QaHistoryMessage(
                role=role, content=content, timestamp=(_qa_now() - _QaDelta(minutes=20)).isoformat(), token_count=5))
    state = _qa_prepare(request)
    if matches:
        state["intent"] = "general"
    return state


def complete_conversation(request, state, answer):
    if not _qa_context.get():
        return _qa_complete(request, state, answer)
    # Run the actual completion and distillation pipeline. Only provider output
    # is controlled: cache reads, idle detection, IDs and Redis writes are real.
    result = _qa_complete(request, state, answer)
    repeated = _qa_memory_write(state)
    assert result["pending_memories"] == repeated["pending_memories"]
    assert len(state["memory_input"]["history"]) == 3
    assert any(m.content == "Later turn must not be distilled" for m in _qa_short.get_history(request.session_id))
    (_qa_root / "snapshot-check.json").write_text(_qa_json.dumps({  # noqa: F821
        "snapshot_frozen": True, "candidate_stable": True, "actual_completion": True,
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
                role="user", content="Later turn must not be distilled", timestamp=_qa_now().isoformat(), token_count=8))
            yield _QaChunk(content="Candidate memory QA verified answer")
        return controlled()


llm = _QaProvider()
_qa_distillation.llm = _QaDistiller()
