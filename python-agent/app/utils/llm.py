import math
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk

from app.core.config import settings
from app.core.logging import setup_logger
from app.core.metrics import (
    LLM_ACTIVE,
    LLM_BUDGET_BLOCKS,
    LLM_ESTIMATED_COST,
    LLM_FALLBACKS,
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    LLM_REQUESTS,
)


logger = setup_logger("llm")


class DeterministicTestLLM:
    """Network-free model used only by explicitly enabled full-stack acceptance tests."""

    @staticmethod
    def _content(messages: Any) -> str:
        return "\n".join(str(getattr(message, "content", message)) for message in messages)

    def _answer(self, messages: Any) -> str:
        prompt = self._content(messages)
        if "intent" in prompt and "confidence" in prompt:
            return '{"intent":"qa","confidence":0.99,"extracted_entities":[]}'
        if "记忆蒸馏器" in prompt or "提取关键信息" in prompt:
            return "[]"
        if "记忆反思器" in prompt or "implicit_preferences" in prompt:
            return '{"implicit_preferences":[],"priority_weak_points":[],"next_step_suggestion":""}'
        return "根据资料，星桥计划的核心识别码是 QZ-7294 [1]。"

    def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:
        return AIMessage(content=self._answer(messages))

    async def ainvoke(self, messages: Any, **kwargs: Any) -> AIMessage:
        return self.invoke(messages, **kwargs)

    async def astream(self, messages: Any, **kwargs: Any) -> AsyncIterator[AIMessageChunk]:
        answer = self._answer(messages)
        for start in range(0, len(answer), 12):
            yield AIMessageChunk(content=answer[start : start + 12])


class FallbackLLM:
    """Lazy LLM client with immediate fallback and circuit breaking."""

    def __init__(self) -> None:
        self._primary: Any | None = None
        self._fallback: Any | None = None
        self._lock = threading.RLock()
        self._failure_count = 0
        self._circuit_opened_at = 0.0
        self._request_times = deque()
        self._budget_day = ""
        self._daily_cost = 0.0
        self._budget_redis: Any | None = None

    @property
    def configured(self) -> bool:
        return bool(
            settings.deterministic_test_llm
            or settings.deepseek_api_key
            or settings.dashscope_api_key
        )

    @property
    def status(self) -> dict[str, Any]:
        if settings.deterministic_test_llm:
            return {
                "configured": True,
                "primary": "deterministic-test",
                "fallback": None,
                "circuit_open": False,
                "failure_count": 0,
            }
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
        if (
            time.monotonic() - self._circuit_opened_at
            >= settings.circuit_recovery_seconds
        ):
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
        if settings.deterministic_test_llm:
            return DeterministicTestLLM(), False
        if not settings.deepseek_api_key:
            fallback = self._get_fallback()
            if fallback is not None:
                return fallback, True
            raise RuntimeError("未配置可用的 LLM API Key")
        if self._is_circuit_open():
            fallback = self._get_fallback()
            if fallback is not None:
                return fallback, True
        return self._get_primary(), False

    def _acquire_quota(self) -> None:
        limit = getattr(settings, "llm_hourly_limit", 0)
        if not limit:
            return
        now = time.monotonic()
        with self._lock:
            while self._request_times and now - self._request_times[0] >= 3600:
                self._request_times.popleft()
            if len(self._request_times) >= limit:
                raise RuntimeError("模型调用额度已用尽，请稍后再试")
            self._request_times.append(now)

    @staticmethod
    def _message_tokens(messages: Any) -> int:
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        return max(1, len(text) // 4)

    @staticmethod
    def _budget_limit() -> float:
        budget = float(getattr(settings, "llm_daily_budget_usd", 0))
        if not math.isfinite(budget) or budget < 0:
            raise RuntimeError("LLM daily budget must be finite and nonnegative")
        return budget

    def _reserve_budget(self, messages: Any, kwargs: dict[str, Any], using_fallback: bool) -> None:
        budget = self._budget_limit()
        if not budget or getattr(settings, "deterministic_test_llm", False):
            return
        provider = "fallback" if using_fallback else "primary"
        input_price = float(getattr(settings, f"llm_{provider}_input_cost_per_million", 0))
        output_price = float(getattr(settings, f"llm_{provider}_output_cost_per_million", 0))
        input_tokens = self._message_tokens(messages)
        if "max_tokens" in kwargs and "max_completion_tokens" in kwargs:
            raise RuntimeError("configure only one output token limit")
        token_key = "max_completion_tokens" if "max_completion_tokens" in kwargs else "max_tokens"
        output_tokens = kwargs.get(token_key, getattr(settings, "llm_default_max_output_tokens", 1024))
        if isinstance(output_tokens, bool) or not isinstance(output_tokens, int) or output_tokens < 1:
            raise RuntimeError("LLM output token limit must be a positive integer")
        # Forward the same limit reserved here to sync, async and streaming providers.
        kwargs[token_key] = output_tokens
        if not all(math.isfinite(price) and price > 0 for price in (input_price, output_price)):
            raise RuntimeError("启用模型日预算时必须配置正数的输入和输出单价")
        estimated = input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            if day != self._budget_day:
                self._budget_day = day
                self._daily_cost = 0.0
            if getattr(settings, "redis_host", ""):
                try:
                    if self._budget_redis is None:
                        from redis import Redis

                        self._budget_redis = Redis(
                            host=settings.redis_host,
                            port=getattr(settings, "redis_port", 6379),
                            db=getattr(settings, "redis_db", 0),
                            password=getattr(settings, "redis_password", "") or None,
                            socket_timeout=2,
                        )
                    total = float(self._budget_redis.eval(
                        "local spent=tonumber(redis.call('GET',KEYS[1]) or '0') "
                        "local charge=tonumber(ARGV[1]) "
                        "if spent+charge>tonumber(ARGV[2]) then return '-1' end "
                        "local total=redis.call('INCRBYFLOAT',KEYS[1],ARGV[1]) "
                        "redis.call('EXPIRE',KEYS[1],172800) return total",
                        1,
                        f"mneme:llm:cost:{day}",
                        estimated,
                        budget,
                    ))
                    if not math.isfinite(total):
                        raise ValueError("budget counter is not finite")
                except Exception as error:
                    raise RuntimeError("模型预算计数服务不可用，调用已拒绝") from error
                if total < 0:
                    LLM_BUDGET_BLOCKS.inc()
                    raise RuntimeError("模型调用将超过当日成本预算，请稍后再试")
                self._daily_cost = total
            else:
                if self._daily_cost + estimated > budget:
                    LLM_BUDGET_BLOCKS.inc()
                    raise RuntimeError("模型调用将超过当日成本预算，请稍后再试")
                self._daily_cost += estimated
        LLM_INPUT_TOKENS.labels(provider).inc(input_tokens)
        LLM_OUTPUT_TOKENS.labels(provider).inc(output_tokens)
        LLM_ESTIMATED_COST.labels(provider).inc(estimated)

    def budget_status(self) -> dict[str, object]:
        budget = self._budget_limit()
        with self._lock:
            day = datetime.now(timezone.utc).date().isoformat()
            if day != self._budget_day:
                self._budget_day = day
                self._daily_cost = 0.0
            if budget and getattr(settings, "redis_host", ""):
                try:
                    if self._budget_redis is None:
                        from redis import Redis

                        self._budget_redis = Redis(
                            host=settings.redis_host,
                            port=getattr(settings, "redis_port", 6379),
                            db=getattr(settings, "redis_db", 0),
                            password=getattr(settings, "redis_password", "") or None,
                            socket_timeout=2,
                        )
                    self._daily_cost = float(
                        self._budget_redis.get(f"mneme:llm:cost:{day}") or 0
                    )
                    if not math.isfinite(self._daily_cost) or self._daily_cost < 0:
                        raise ValueError("budget counter is invalid")
                except Exception:
                    return {
                        "daily_budget_usd": budget,
                        "daily_spend_usd": None,
                        "remaining_usd": None,
                        "enabled": True,
                        "status": "unavailable",
                    }
            return {
                "daily_budget_usd": budget,
                "daily_spend_usd": round(self._daily_cost, 8),
                "cost_basis": "reservation_estimate",
                "remaining_usd": round(max(0.0, budget - self._daily_cost), 8) if budget else None,
                "enabled": bool(budget),
                "status": "ready" if budget else "disabled",
            }

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        model, using_fallback = self._selected()
        self._reserve_budget(messages, kwargs, using_fallback)
        try:
            result = model.invoke(messages, **kwargs)
            if not using_fallback:
                self._record_success()
            LLM_REQUESTS.labels(
                "sync", "fallback" if using_fallback else "primary", "success"
            ).inc()
            return result
        except Exception as error:
            LLM_REQUESTS.labels(
                "sync", "fallback" if using_fallback else "primary", "failure"
            ).inc()
            if using_fallback:
                raise
            self._record_failure(error)
            fallback = self._get_fallback()
            if fallback is None:
                raise
            self._reserve_budget(messages, kwargs, True)
            logger.info("当前请求切换至备用模型 %s", settings.fallback_model)
            LLM_FALLBACKS.labels("sync").inc()
            result = fallback.invoke(messages, **kwargs)
            LLM_REQUESTS.labels("sync", "fallback", "success").inc()
            return result

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        model, using_fallback = self._selected()
        self._reserve_budget(messages, kwargs, using_fallback)
        try:
            result = await model.ainvoke(messages, **kwargs)
            if not using_fallback:
                self._record_success()
            LLM_REQUESTS.labels(
                "async", "fallback" if using_fallback else "primary", "success"
            ).inc()
            return result
        except Exception as error:
            LLM_REQUESTS.labels(
                "async", "fallback" if using_fallback else "primary", "failure"
            ).inc()
            if using_fallback:
                raise
            self._record_failure(error)
            fallback = self._get_fallback()
            if fallback is None:
                raise
            self._reserve_budget(messages, kwargs, True)
            logger.info("当前异步请求切换至备用模型 %s", settings.fallback_model)
            LLM_FALLBACKS.labels("async").inc()
            result = await fallback.ainvoke(messages, **kwargs)
            LLM_REQUESTS.labels("async", "fallback", "success").inc()
            return result

    async def astream(self, messages: Any, **kwargs: Any) -> AsyncIterator[Any]:
        self._acquire_quota()
        LLM_ACTIVE.inc()
        emitted = False
        try:
            model, using_fallback = self._selected()
            self._reserve_budget(messages, kwargs, using_fallback)
            try:
                async for chunk in model.astream(messages, **kwargs):
                    emitted = True
                    yield chunk
                if not using_fallback:
                    self._record_success()
                LLM_REQUESTS.labels(
                    "stream", "fallback" if using_fallback else "primary", "success"
                ).inc()
            except Exception as error:
                LLM_REQUESTS.labels(
                    "stream", "fallback" if using_fallback else "primary", "failure"
                ).inc()
                if using_fallback or emitted:
                    raise
                self._record_failure(error)
                fallback = self._get_fallback()
                if fallback is None:
                    raise
                self._reserve_budget(messages, kwargs, True)
                logger.info("流式请求切换至备用模型 %s", settings.fallback_model)
                LLM_FALLBACKS.labels("stream").inc()
                async for chunk in fallback.astream(messages, **kwargs):
                    yield chunk
                LLM_REQUESTS.labels("stream", "fallback", "success").inc()
        finally:
            LLM_ACTIVE.dec()


llm = FallbackLLM()
