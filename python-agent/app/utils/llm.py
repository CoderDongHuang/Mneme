"""
LLM 客户端 — 支持主备切换与熔断降级

- 主模型: DeepSeek-V3 (deepseek-chat)
- 备选模型: 通义千问 (qwen-plus) 或其他 OpenAI 兼容模型
- 熔断: 连续失败 N 次后自动切备选，探测恢复后切回主模型
"""
import time
import threading
from langchain_deepseek import ChatDeepSeek
from langchain_core.language_models import BaseChatModel
from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("llm")


class FallbackLLM:
    """带熔断降级的 LLM 客户端"""

    def __init__(self):
        self._primary = ChatDeepSeek(
            model="deepseek-chat",
            api_key=settings.DEEPSEEK_API_KEY,
            temperature=0.7,
        )
        self._fallback = self._build_fallback()
        self._lock = threading.Lock()
        self._failure_count = 0
        self._circuit_open = False
        self._last_failure_time = 0.0
        self._recovery_probe_interval = 60

    def _build_fallback(self) -> BaseChatModel:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=settings.LLM_FALLBACK_MODEL,
                api_key=settings.DASHSCOPE_API_KEY,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                temperature=0.7,
            )
        except ImportError:
            logger.warning("langchain_openai 不可用，备选模型降级为 DeepSeek")
            return self._primary

    @property
    def _active_model(self) -> BaseChatModel:
        if not settings.LLM_FALLBACK_ENABLED:
            return self._primary
        with self._lock:
            if self._circuit_open:
                elapsed = time.time() - self._last_failure_time
                if elapsed > self._recovery_probe_interval:
                    logger.info("探测主模型恢复...")
                    self._circuit_open = False
                    self._failure_count = 0
                    return self._primary
                return self._fallback
            return self._primary

    def _on_success(self):
        with self._lock:
            self._failure_count = 0
            if self._circuit_open:
                logger.info("主模型已恢复，切回 DeepSeek")
                self._circuit_open = False

    def _on_failure(self, error: Exception):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if (
                self._failure_count >= settings.LLM_CIRCUIT_BREAKER_THRESHOLD
                and not self._circuit_open
            ):
                self._circuit_open = True
                logger.warning(
                    f"主模型连续失败 {self._failure_count} 次，切换到备选模型"
                )

    # ── LangChain 兼容接口 ──

    def invoke(self, messages, **kwargs):
        try:
            result = self._active_model.invoke(messages, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            if self._circuit_open and self._active_model is self._fallback:
                logger.info(f"主模型不可用，使用备选: {settings.LLM_FALLBACK_MODEL}")
                return self._fallback.invoke(messages, **kwargs)
            raise

    async def ainvoke(self, messages, **kwargs):
        try:
            result = await self._active_model.ainvoke(messages, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            if self._circuit_open and self._active_model is self._fallback:
                logger.info("主模型不可用（异步），使用备选模型")
                return await self._fallback.ainvoke(messages, **kwargs)
            raise

    async def astream(self, messages, **kwargs):
        try:
            async for chunk in self._active_model.astream(messages, **kwargs):
                yield chunk
            self._on_success()
        except Exception as e:
            self._on_failure(e)
            if self._circuit_open and self._active_model is self._fallback:
                logger.info(f"主模型流式不可用，切换备选 {settings.LLM_FALLBACK_MODEL}")
                async for chunk in self._fallback.astream(messages, **kwargs):
                    yield chunk
            else:
                raise

    def __getattr__(self, name):
        return getattr(self._primary, name)


llm = FallbackLLM()
