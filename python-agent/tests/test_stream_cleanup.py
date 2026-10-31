import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import anyio
import pytest
from langchain_core.messages import AIMessageChunk

from app.models.chat import ChatRequest


class ProviderStream:
    def __init__(self, mode="normal"):
        self.mode = mode
        self.reads = 0
        self.closes = 0
        self.started = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.started.set()
        self.reads += 1
        if self.mode == "blocked":
            await asyncio.Event().wait()
        if self.mode == "error":
            raise RuntimeError("provider failed")
        if self.reads > 2:
            raise StopAsyncIteration
        return AIMessageChunk(content="answer")

    async def aclose(self):
        # A real SDK may await socket cleanup; test that ASGI cancellation does
        # not cancel this await and leave an open provider connection.
        await anyio.sleep(0.001)
        self.closes += 1


def configure(monkeypatch, provider, timeout=1):
    import app.api.chat_stream as module

    monkeypatch.setattr(module, "prepare_conversation", lambda _: {"intent": "general"})
    monkeypatch.setattr(module, "build_llm_prompt", lambda _: "prompt")
    complete = Mock(return_value={})
    monkeypatch.setattr(module, "complete_conversation", complete)
    monkeypatch.setattr(module, "settings", SimpleNamespace(stream_timeout_seconds=timeout))
    monkeypatch.setattr(module, "llm", SimpleNamespace(astream=lambda *args: provider))
    return module, complete


@pytest.mark.parametrize("mode", ["normal", "error", "blocked"])
def test_upstream_closed_on_completion_error_and_timeout(monkeypatch, mode):
    async def run():
        provider = ProviderStream(mode)
        module, complete = configure(monkeypatch, provider, timeout=0.01)
        response = await module.chat_stream(ChatRequest(user_id="qa", session_id="qa", message="hello"))
        events = [event async for event in response.body_iterator]
        assert provider.closes == 1
        assert any("event: error" in event for event in events) == (mode == "error")
        if mode == "error":
            assert any('"code": "MODEL_ERROR"' in event for event in events)
        assert complete.call_count == (0 if mode == "error" else 1)
    asyncio.run(run())


def test_explicit_stop_closes_nested_generator_before_return(monkeypatch):
    async def run():
        provider = ProviderStream()
        module, complete = configure(monkeypatch, provider)
        response = await module.chat_stream(ChatRequest(user_id="qa", session_id="qa", message="hello"))
        stream = response.body_iterator
        assert "event: meta" in await anext(stream)
        assert "event: token" in await anext(stream)
        await stream.aclose()
        assert provider.closes == 1 and provider.reads == 1
        complete.assert_not_called()
    asyncio.run(run())


def test_cancelling_pending_provider_read_closes_without_memory_or_error_event(monkeypatch):
    async def run():
        provider = ProviderStream("blocked")
        module, complete = configure(monkeypatch, provider)
        response = await module.chat_stream(ChatRequest(user_id="qa", session_id="qa", message="hello"))
        stream = response.body_iterator
        await anext(stream)
        task = asyncio.create_task(anext(stream))
        await provider.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider.closes == 1
        complete.assert_not_called()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["disconnect", "send_error"])
def test_asgi_disconnect_or_broken_send_closes_provider_while_paused_at_yield(monkeypatch, failure):
    async def run():
        provider = ProviderStream()
        module, complete = configure(monkeypatch, provider)
        response = await module.chat_stream(ChatRequest(user_id="qa", session_id="qa", message="hello"))
        disconnect = asyncio.Event()

        async def receive():
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if b"event: token" in message.get("body", b""):
                if failure == "send_error":
                    raise OSError("socket closed")
                disconnect.set()
                await asyncio.Event().wait()  # cancelled while generator paused

        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert provider.closes == 1 and provider.reads == 1
        complete.assert_not_called()
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["primary", "fallback", "personal"])
def test_llm_wrapper_closes_actual_provider_and_releases_active_gauge(monkeypatch, kind):
    from app.utils import llm as module
    from app.core.user_model import user_model

    async def run():
        provider = ProviderStream()
        wrapper = module.FallbackLLM()
        monkeypatch.setattr(wrapper, "_acquire_quota", lambda: None)
        monkeypatch.setattr(wrapper, "_reserve_budget", lambda *args: None)
        monkeypatch.setattr(wrapper, "_selected", lambda: (SimpleNamespace(astream=lambda *a, **kw: provider), False))
        if kind == "fallback":
            async def failed(*args, **kwargs):
                raise RuntimeError("primary failed")
                yield
            monkeypatch.setattr(wrapper, "_selected", lambda: (SimpleNamespace(astream=failed), False))
            monkeypatch.setattr(wrapper, "_get_fallback", lambda: SimpleNamespace(astream=lambda *a, **kw: provider))
        token = user_model.set(SimpleNamespace(get_client=lambda: SimpleNamespace(astream=lambda *a, **kw: provider)) if kind == "personal" else None)
        try:
            before = module.LLM_ACTIVE._value.get()
            stream = wrapper.astream([])
            await anext(stream)
            await stream.aclose()
            assert provider.closes == 1 and provider.reads == 1
            assert module.LLM_ACTIVE._value.get() == before
        finally:
            user_model.reset(token)
    asyncio.run(run())


def test_real_http_disconnect_releases_provider(monkeypatch):
    """Exercise actual TCP disconnect detection rather than waiting for GC."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn
    from fastapi import FastAPI

    provider = ProviderStream()
    module, complete = configure(monkeypatch, provider, timeout=30)

    async def slow_next():
        provider.reads += 1
        if provider.reads > 1:
            await asyncio.Event().wait()
        return AIMessageChunk(content="answer")

    # Special methods are resolved on the type, not the instance.
    monkeypatch.setattr(ProviderStream, "__anext__", lambda self: slow_next())
    app = FastAPI()
    app.include_router(module.router)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(trust_env=False) as client:
            with client.stream("POST", f"http://127.0.0.1:{sock.getsockname()[1]}/api/v1/chat/stream",
                               json={"user_id": "qa", "session_id": "qa", "message": "hello"}) as response:
                assert response.status_code == 200
                for line in response.iter_lines():
                    if line == "event: token":
                        break
        deadline = time.monotonic() + 2
        while not provider.closes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert provider.closes == 1
        complete.assert_not_called()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
