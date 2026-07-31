import threading
import time
from collections import deque
from typing import Any, AsyncIterator

from app.core.config import settings
from app.core.logging import setup_logger
from app.core.metrics import LLM_ACTIVE, LLM_FALLBACKS, LLM_REQUESTS


logger = setup_logger("llm")


class FallbackLLM:
    """Lazy LLM client with immediate fallback and circuit breaking."""

    def __init__(self) -> None:
        self._primary: Any | None = None
        self._fallback: Any | None = None
        self._lock = threading.RLock()
        self._failure_count = 0
        self._circuit_opened_at = 0.0
        self._request_times = deque()

    @property
    def configured(self) -> bool:
        return bool(settings.deepseek_api_key or settings.dashscope_api_key)

    @property
    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "primary": settings.deepseek_model,
            "fallback": settings.fallback_model if settings.fallback_enabled else None,
            "circuit_open": self._is_circuit_open(),
            "failure_count": self._failure_count,
        }

    def _build_primary(self) -> Any:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            temperature=0.4,
            timeout=35,
            max_retries=1,
        )

    def _build_fallback(self) -> Any:
        if not settings.fallback_enabled or not settings.dashscope_api_key:
            return None
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            logger.warning("未安装 langchain-openai，Qwen 备用模型不可用")
            return None
        return ChatOpenAI(
            model=settings.fallback_model,
            api_key=settings.dashscope_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=0.4,
            timeout=35,
            max_retries=1,
        )

    def _get_primary(self) -> Any:
        with self._lock:
            if self._primary is None:
                self._primary = self._build_primary()
            return self._primary

    def _get_fallback(self) -> Any | None:
        with self._lock:
            if self._fallback is None:
                self._fallback = self._build_fallback()
            return self._fallback

    def _is_circuit_open(self) -> bool:
        if not self._circuit_opened_at:
            return False
        if time.monotonic() - self._circuit_opened_at >= settings.circuit_recovery_seconds:
            with self._lock:
                self._circuit_opened_at = 0.0
                self._failure_count = 0
            logger.info("LLM 主模型熔断恢复，下一次请求将探测主模型")
            return False
        return True

    def _record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._circuit_opened_at = 0.0

    def _record_failure(self, error: Exception) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= settings.circuit_breaker_threshold:
                self._circuit_opened_at = time.monotonic()
        logger.warning("LLM 主模型调用失败: %s", error)

    def _selected(self) -> tuple[Any, bool]:
        if self._is_circuit_open():
            fallback = self._get_fallback()
            if fallback is not None:
                return fallback, True
        return self._get_primary(), False

    def _acquire_quota(self) -> None:
        limit = settings.llm_hourly_limit
        if not limit:
            return
        now = time.monotonic()
        with self._lock:
            while self._request_times and now - self._request_times[0] >= 3600:
                self._request_times.popleft()
            if len(self._request_times) >= limit:
                raise RuntimeError("模型调用额度已用尽，请稍后再试")
            self._request_times.append(now)

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        model, using_fallback = self._selected()
        try:
            result = model.invoke(messages, **kwargs)
            if not using_fallback:
                self._record_success()
            LLM_REQUESTS.labels("sync", "fallback" if using_fallback else "primary", "success").inc()
            return result
        except Exception as error:
            LLM_REQUESTS.labels("sync", "fallback" if using_fallback else "primary", "failure").inc()
            if using_fallback:
                raise
            self._record_failure(error)
            fallback = self._get_fallback()
            if fallback is None:
                raise
            logger.info("当前请求切换至备用模型 %s", settings.fallback_model)
            LLM_FALLBACKS.labels("sync").inc()
            result = fallback.invoke(messages, **kwargs)
            LLM_REQUESTS.labels("sync", "fallback", "success").inc()
            return result

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        model, using_fallback = self._selected()
        try:
            result = await model.ainvoke(messages, **kwargs)
            if not using_fallback:
                self._record_success()
            LLM_REQUESTS.labels("async", "fallback" if using_fallback else "primary", "success").inc()
            return result
        except Exception as error:
            LLM_REQUESTS.labels("async", "fallback" if using_fallback else "primary", "failure").inc()
            if using_fallback:
                raise
            self._record_failure(error)
            fallback = self._get_fallback()
            if fallback is None:
                raise
            logger.info("当前异步请求切换至备用模型 %s", settings.fallback_model)
            LLM_FALLBACKS.labels("async").inc()
            result = await fallback.ainvoke(messages, **kwargs)
            LLM_REQUESTS.labels("async", "fallback", "success").inc()
            return result

    async def astream(self, messages: Any, **kwargs: Any) -> AsyncIterator[Any]:
        self._acquire_quota()
        LLM_ACTIVE.inc()
        model, using_fallback = self._selected()
        emitted = False
        try:
            async for chunk in model.astream(messages, **kwargs):
                emitted = True
                yield chunk
            if not using_fallback:
                self._record_success()
            LLM_REQUESTS.labels("stream", "fallback" if using_fallback else "primary", "success").inc()
        except Exception as error:
            LLM_REQUESTS.labels("stream", "fallback" if using_fallback else "primary", "failure").inc()
            if using_fallback or emitted:
                raise
            self._record_failure(error)
            fallback = self._get_fallback()
            if fallback is None:
                raise
            logger.info("流式请求切换至备用模型 %s", settings.fallback_model)
            LLM_FALLBACKS.labels("stream").inc()
            async for chunk in fallback.astream(messages, **kwargs):
                yield chunk
            LLM_REQUESTS.labels("stream", "fallback", "success").inc()
        finally:
            LLM_ACTIVE.dec()


llm = FallbackLLM()
