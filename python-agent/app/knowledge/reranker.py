"""Configurable DashScope or local Cross Encoder reranking."""

from functools import lru_cache
import math
from typing import Any

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("reranker")


@lru_cache(maxsize=1)
def _load_model() -> Any | None:
    if (
        not settings.reranker_enabled
        or not settings.reranker_model
        or settings.reranker_provider != "cross_encoder"
    ):
        return None
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(settings.reranker_model)
    except (ImportError, OSError, RuntimeError) as error:
        logger.warning("Cross Encoder 不可用，保留混合召回排序: %s", error)
        return None


def rerank(query: str, candidates: list[dict], limit: int) -> list[dict]:
    """对候选片段重排；模型缺失或推理失败时确定性降级。"""
    if not candidates:
        return []
    if getattr(settings, "demo_mode", False):
        return candidates[:limit]
    if settings.reranker_enabled and settings.reranker_provider == "dashscope":
        if not math.isfinite(settings.reranker_min_score) or not 0 <= settings.reranker_min_score <= 1:
            raise ValueError("RERANKER_MIN_SCORE must be a finite value between 0 and 1")
        ranked = _dashscope_rerank(query, candidates, limit)
        if ranked is not None:
            return ranked
    model = _load_model()
    if model is None:
        return candidates[:limit]
    try:
        scores = model.predict(
            [(query, str(candidate.get("content", ""))) for candidate in candidates]
        )
        ranked = []
        for candidate, score in zip(candidates, scores):
            ranked.append({**candidate, "rerank_score": float(score)})
        ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        return ranked[:limit]
    except Exception as error:
        logger.warning("Cross Encoder 重排失败，保留混合召回排序: %s", error)
        return candidates[:limit]


def _dashscope_rerank(
    query: str, candidates: list[dict], limit: int
) -> list[dict] | None:
    if not settings.dashscope_api_key:
        return None
    try:
        import dashscope

        response = dashscope.TextReRank.call(
            model=settings.reranker_model,
            query=query,
            documents=[str(candidate.get("content", "")) for candidate in candidates],
            top_n=min(limit, len(candidates)),
            return_documents=False,
            api_key=settings.dashscope_api_key,
            timeout=10,
        )
        if getattr(response, "status_code", 500) != 200:
            raise RuntimeError(getattr(response, "message", "DashScope rerank failed"))
        output = getattr(response, "output", {}) or {}
        results = output.get("results", []) if isinstance(output, dict) else getattr(output, "results", [])
        ranked = []
        seen = set()
        for result in results:
            index = result.get("index") if isinstance(result, dict) else result.index
            score = result.get("relevance_score") if isinstance(result, dict) else result.relevance_score
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(candidates) or index in seen:
                raise ValueError("Invalid reranker candidate index")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("Invalid normalized reranker score")
            seen.add(index)
            if score >= settings.reranker_min_score:
                ranked.append({**candidates[index], "rerank_score": float(score)})
        ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        # An empty successful response is evidence absence, not a provider failure.
        return ranked[:limit]
    except Exception as error:
        logger.warning("DashScope 重排失败，保留混合召回排序: %s", error)
        return None
