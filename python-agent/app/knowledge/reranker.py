"""可选 Cross Encoder 重排器，默认不加载大型模型依赖。"""

from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("reranker")


@lru_cache(maxsize=1)
def _load_model() -> Any | None:
    if not settings.reranker_enabled or not settings.reranker_model:
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
