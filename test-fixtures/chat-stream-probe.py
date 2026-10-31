"""Test-only scoped provider; loaded explicitly by the real-stack E2E harness.

Never imported by production. The harness backs up/restores the exact module
bytes, restarts the service and removes the temporary scope in its finally.
"""
import asyncio as _qa_asyncio
import contextvars as _qa_contextvars
import json as _qa_json
import time as _qa_time
from pathlib import Path as _QaPath
from langchain_core.messages import AIMessageChunk as _QaChunk

_qa_context = _qa_contextvars.ContextVar("stream_probe", default=None)
_qa_prepare = prepare_conversation  # noqa: F821 -- injected module globals
_qa_llm = llm  # noqa: F821


def prepare_conversation(request):
    state = _qa_prepare(request)
    _qa_context.set(None)
    scope = _qa_json.loads((_qa_root / "scope.json").read_text())  # noqa: F821
    mode = scope["sessions"].get(str(request.session_id))
    if str(request.user_id) == scope["user"] and mode in ("partial", "silent"):
        _qa_context.set((str(request.session_id), mode))
        state["intent"] = "general"
    return state


class _QaProvider:
    def __getattr__(self, name):
        return getattr(_qa_llm, name)

    def astream(self, messages, **kwargs):
        target = _qa_context.get()
        if target is None:
            return _qa_llm.astream(messages, **kwargs)

        async def controlled():
            session, mode = target
            marker = _qa_root / (session + ".json")  # noqa: F821
            state = {"started": _qa_time.monotonic(), "closed": None}
            marker.write_text(_qa_json.dumps(state))
            try:
                if mode == "partial":
                    yield _QaChunk(content="Stream QA partial answer")
                await _qa_asyncio.Event().wait()
            finally:
                state["closed"] = _qa_time.monotonic()
                marker.write_text(_qa_json.dumps(state))

        return controlled()


llm = _QaProvider()
