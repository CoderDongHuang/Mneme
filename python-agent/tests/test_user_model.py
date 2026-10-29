import asyncio
import base64
import json
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from app.core.user_model import UserModel, UserModelMiddleware, user_model
from app.utils.llm import FallbackLLM


def test_personal_failure_never_uses_server_fallback():
    client = Mock()
    client.invoke.side_effect = RuntimeError("provider failure")
    wrapper = FallbackLLM()
    wrapper._get_fallback = Mock()
    token = user_model.set(UserModel("openai", "personal-model", "private", client))
    try:
        with pytest.raises(RuntimeError, match="provider failure"):
            wrapper.invoke([])
        wrapper._get_fallback.assert_not_called()
    finally:
        user_model.reset(token)
    assert user_model.get() is None


def test_concurrent_async_and_streaming_requests_keep_their_model():
    async def run():
        wrapper = FallbackLLM()

        async def one(name):
            client = Mock()
            async def invoke(*args, **kwargs):
                await asyncio.sleep(0)
                return AIMessage(content=user_model.get().model)
            async def stream(*args, **kwargs):
                for _ in range(2):
                    await asyncio.sleep(0)
                    yield AIMessageChunk(content=user_model.get().model)
            client.ainvoke = invoke
            client.astream = stream
            token = user_model.set(UserModel("openai", name, "private", client))
            try:
                result = await wrapper.ainvoke([])
                chunks = [chunk.content async for chunk in wrapper.astream([])]
                assert result.content == name
                assert chunks == [name, name]
            finally:
                user_model.reset(token)
        await asyncio.gather(one("alice"), one("bob"))
        assert user_model.get() is None
    asyncio.run(run())


def test_middleware_rejects_untrusted_and_invalid_configuration(monkeypatch):
    from app.core import user_model as module
    monkeypatch.setattr(module.internal_tokens, "accepts", lambda supplied: supplied == "trusted")
    async def run(header, token):
        downstream = AsyncMock()
        send = AsyncMock()
        scope = {"type": "http", "headers": [(b"x-mneme-model", header), (b"x-internal-service-token", token)]}
        await UserModelMiddleware(downstream)(scope, AsyncMock(), send)
        downstream.assert_not_called()
        return send.call_args_list[0].args[0]["status"]
    encoded = base64.b64encode(json.dumps({"provider": "openai", "model": "test", "apiKey": "secret", "baseUrl": "http://internal"}).encode())
    assert asyncio.run(run(encoded, b"untrusted")) == 401
    assert asyncio.run(run(encoded, b"trusted")) == 400
    assert asyncio.run(run(b"not base64", b"trusted")) == 400
