"""Request-scoped model credentials. Never cached in a process-wide model client."""
import base64
import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from starlette.responses import JSONResponse

from app.core.internal_tokens import internal_tokens


PROVIDERS = {
    "deepseek": "https://api.deepseek.com/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai": "https://api.openai.com/v1",
}


@dataclass
class UserModel:
    provider: str
    model: str
    api_key: str = field(repr=False)
    client: Any = field(default=None, repr=False)

    def get_client(self):
        if self.client is None:
            from langchain_openai import ChatOpenAI

            self.client = ChatOpenAI(
                model=self.model, api_key=self.api_key, base_url=PROVIDERS[self.provider],
                temperature=0.4, timeout=35, max_retries=1,
            )
        return self.client


user_model: ContextVar[UserModel | None] = ContextVar("user_model", default=None)


class UserModelMiddleware:
    """The context remains bound until the entire streaming response is sent."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        encoded = headers.get(b"x-mneme-model")
        config = None
        if encoded:
            # Even development's SKIP_INTERNAL_AUTH must not trust supplied credentials.
            supplied = headers.get(b"x-internal-service-token", b"").decode("latin1")
            if not internal_tokens.accepts(supplied):
                await JSONResponse({"detail": "Unauthorized model configuration"}, status_code=401)(scope, receive, send)
                return
            try:
                import re

                if len(encoded) > 4096:
                    raise ValueError("too large")
                body = json.loads(base64.b64decode(encoded, validate=True))
                provider, model, api_key = body["provider"], body["model"], body["apiKey"]
                if provider not in PROVIDERS or body.get("baseUrl") != PROVIDERS[provider]:
                    raise ValueError("provider")
                if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,120}", model):
                    raise ValueError("model")
                if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 512 or any(ord(c) < 32 for c in api_key):
                    raise ValueError("key")
                config = UserModel(provider, model, api_key)
            except (ValueError, KeyError, TypeError):
                await JSONResponse({"detail": "Invalid model configuration"}, status_code=400)(scope, receive, send)
                return
        token = user_model.set(config)
        try:
            await self.app(scope, receive, send)
        finally:
            user_model.reset(token)
