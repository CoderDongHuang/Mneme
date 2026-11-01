"""Scoped real-stack provider/candidate fixture, installed and restored by E2E only."""
import contextvars as _qa_contextvars
import json as _qa_json
from langchain_core.messages import AIMessageChunk as _QaChunk

_qa_context = _qa_contextvars.ContextVar("memory_outbox_probe", default=False)
_qa_prepare = prepare_conversation  # noqa: F821 -- injected module globals
_qa_complete = complete_conversation  # noqa: F821
_qa_llm = llm  # noqa: F821


def prepare_conversation(request):
    state = _qa_prepare(request)
    scope = _qa_json.loads((_qa_root / "scope.json").read_text())  # noqa: F821
    matches = str(request.user_id) == scope["user"] and str(request.session_id) == scope["session"]
    _qa_context.set(matches)
    if matches:
        state["intent"] = "general"
    return state


def complete_conversation(request, state, answer):
    if not _qa_context.get():
        return _qa_complete(request, state, answer)
    scope = _qa_json.loads((_qa_root / "scope.json").read_text())  # noqa: F821
    return {"pending_memories": [{
        "temp_id": scope["memory"], "category": "preference", "content": "Candidate memory QA preference",
        "topic": "Memory outbox QA", "confidence": 0.8,
    }]}


class _QaProvider:
    def __getattr__(self, name):
        return getattr(_qa_llm, name)

    def astream(self, messages, **kwargs):
        if not _qa_context.get():
            return _qa_llm.astream(messages, **kwargs)

        async def controlled():
            yield _QaChunk(content="Candidate memory QA verified answer")
        return controlled()


llm = _QaProvider()
