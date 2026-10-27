"""Bounded, cached probes using synthetic content and server-owned credentials only."""
import asyncio
import time

import httpx

from app.core.config import settings
from app.utils.embedding import embeddings
from app.utils.llm import llm

_lock = asyncio.Lock()
_cached = None
_cached_at = 0.0


def profiles():
    return {
        "chat": {"provider": "local" if settings.demo_mode else "deepseek" if settings.deepseek_api_key else "dashscope",
                 "model": llm.status["primary"] if settings.demo_mode or settings.deepseek_api_key else settings.fallback_model,
                 "fallback": llm.status.get("fallback") if settings.deepseek_api_key else None,
                 "configured": llm.configured, "timeout_seconds": 35, "max_retries": 1,
                 "hourly_limit": settings.llm_hourly_limit},
        "embedding": {"provider": "local" if embeddings._should_use_offline() else "dashscope",
                      "model": embeddings.profile(), "configured": True,
                      "timeout_seconds": 10, "max_retries": 0},
        "rerank": {"provider": settings.reranker_provider, "model": settings.reranker_model,
                   "enabled": settings.reranker_enabled and not settings.demo_mode,
                   "configured": bool(settings.dashscope_api_key) if settings.reranker_provider == "dashscope" else True,
                   "timeout_seconds": 10, "max_retries": 0},
        "ocr": {"provider": "tesseract", "model": settings.ocr_languages,
                "enabled": settings.ocr_enabled, "timeout_seconds": 10, "max_retries": 0,
                "vision_model": settings.multimodal_model if settings.multimodal_enabled else "disabled"},
    }


def classify_error(error):
    if error.__cause__ is not None:
        return classify_error(error.__cause__)
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if status in (401, 403):
        return "authentication_failed"
    if status == 429:
        return "quota_or_rate_limit"
    if status in (400, 404):
        return "model_unsupported"
    if isinstance(error, (ImportError, FileNotFoundError)) or type(error).__name__ == "TesseractNotFoundError":
        return "runtime_missing"
    return "provider_or_network_error"


async def _probe(name):
    profile = profiles()[name]
    started = time.monotonic()
    state = "ok"
    try:
        if profile.get("enabled") is False:
            state = "disabled"
        elif not profile.get("configured", True):
            state = "missing_credentials"
        elif name == "chat":
            if not settings.demo_mode and not (settings.deepseek_api_key or settings.dashscope_api_key):
                state = "missing_credentials"
            else:
                # Probe the configured primary directly; automatic fallback must not
                # turn a broken primary into a green diagnostic result.
                model = llm._selected()[0] if settings.demo_mode else (
                    llm._get_primary() if settings.deepseek_api_key else llm._get_fallback())
                if model is None:
                    state = "missing_credentials"
                else:
                    await asyncio.wait_for(model.ainvoke([("human", "Reply with OK. Synthetic connectivity test.")], max_tokens=16), 15)
        elif name == "embedding":
            await asyncio.wait_for(asyncio.to_thread(embeddings, ["Synthetic Mneme connectivity test"]), 15)
        elif name == "rerank":
            if settings.reranker_provider != "dashscope":
                from app.knowledge.reranker import _load_model
                # A status button must not start an unbounded model download.
                if not _load_model.cache_info().currsize:
                    state = "model_not_loaded"
                else:
                    model = _load_model()
                    if model is None:
                        state = "runtime_missing"
                    else:
                        await asyncio.wait_for(asyncio.to_thread(model.predict, [("Mneme", "Mneme synthetic example")]), 15)
            else:
                # Direct request: do not hide provider failures behind rerank fallback.
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post("https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
                        headers={"Authorization": "Bearer " + settings.dashscope_api_key},
                        json={"model": settings.reranker_model,
                              "input": {"query": "Mneme", "documents": ["Mneme synthetic example"]},
                              "parameters": {"top_n": 1}})
                    if response.status_code != 200:
                        error = RuntimeError("Provider rejected synthetic probe")
                        error.status_code = response.status_code
                        raise error
        else:
            import pytesseract
            from PIL import Image
            def check_ocr():
                languages = set(pytesseract.get_languages(config=""))
                if not set(settings.ocr_languages.split("+")).issubset(languages):
                    raise FileNotFoundError("OCR language pack missing")
                pytesseract.image_to_string(Image.new("RGB", (80, 30), "white"),
                                           lang=settings.ocr_languages, timeout=10)
            await asyncio.wait_for(asyncio.to_thread(check_ocr), 15)
    except Exception as error:
        state = classify_error(error)
    return {"state": state, "latency_ms": round((time.monotonic() - started) * 1000)}


async def check_providers():
    global _cached, _cached_at
    async with _lock:
        if _cached is not None and time.monotonic() - _cached_at < 60:
            return {**_cached, "cached": True}
        names = ["chat", "embedding", "rerank", "ocr"]
        values = await asyncio.gather(*(_probe(name) for name in names))
        _cached = {"results": dict(zip(names, values)), "cached": False, "cache_seconds": 60}
        _cached_at = time.monotonic()
        return _cached
