"""Explicit E2E-only bad upstream frames, isolated to newly created QA sessions.

The harness restores the exact production module and restarts in finally.
The production serializer remains active for every other user and payload.
"""
import asyncio as _qa_asyncio
import contextvars as _qa_contextvars
import json as _qa_json
from langchain_core.messages import AIMessageChunk as _QaChunk

_qa_target = _qa_contextvars.ContextVar("contract_probe", default=None)
_qa_prepare = prepare_conversation  # noqa: F821 -- injected module globals
_qa_llm = llm  # noqa: F821
_qa_event = _event  # noqa: F821


def prepare_conversation(request):
    _qa_target.set(None)
    state = _qa_prepare(request)
    scope = _qa_json.loads((_qa_root / "scope.json").read_text())  # noqa: F821
    mode = scope["sessions"].get(str(request.session_id))
    if str(request.user_id) == scope["user"] and mode in ("type", "json"):
        _qa_target.set((str(request.session_id), mode, scope["canary"]))
        state["intent"] = "general"
    return state


def _event(event, payload):
    target = _qa_target.get()
    if target and event == "token" and payload.get("content") == "contract-probe-invalid":
        if target[1] == "json":
            return "event: token\ndata: not-json-" + target[2] + "\n\n"
        return "event: token\ndata: " + _qa_json.dumps({"content": 123, "private": target[2]}) + "\n\n"
    return _qa_event(event, payload)


class _QaProvider:
    def __getattr__(self, name):
        return getattr(_qa_llm, name)

    def astream(self, messages, **kwargs):
        target = _qa_target.get()
        if target is None:
            return _qa_llm.astream(messages, **kwargs)

        async def controlled():
            marker = _qa_root / (target[0] + ".json")  # noqa: F821
            try:
                yield _QaChunk(content="Contract QA retained partial answer")
                yield _QaChunk(content="contract-probe-invalid")
                await _qa_asyncio.Event().wait()
            finally:
                marker.write_text(_qa_json.dumps({"closed": True}))
        return controlled()


llm = _QaProvider()
