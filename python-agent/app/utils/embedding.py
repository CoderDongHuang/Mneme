import hashlib
import math
import os
from typing import Any

from chromadb import Documents, EmbeddingFunction, Embeddings

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("embedding")
EMBEDDING_DIMENSION = 1024


def _offline_embedding(text: str) -> list[float]:
    """Deterministic fallback used for tests and unconfigured local startup."""
    vector = [0.0] * EMBEDDING_DIMENSION
    normalized = " ".join(text.lower().split())
    tokens = [
        normalized[index : index + 3] for index in range(max(1, len(normalized) - 2))
    ]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSION
        vector[index] += -1.0 if digest[4] & 1 else 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class DashScopeEmbeddingFunction(EmbeddingFunction):
    def __init__(self) -> None:
        self._warned_offline = False

    def name(self) -> str:
        return "mneme-dashscope-embedding"

    def _should_use_offline(self) -> bool:
        key = settings.dashscope_api_key
        return (
            not key
            or key.startswith("ci-dummy")
            or bool(os.getenv("PYTEST_CURRENT_TEST"))
            or os.getenv("MNEME_OFFLINE_EMBEDDINGS", "").lower() == "true"
        )

    def _call_dashscope(self, texts: list[str]) -> list[list[float]]:
        import dashscope

        response: Any = dashscope.TextEmbedding.call(
            model=settings.embedding_model,
            input=texts,
            api_key=settings.dashscope_api_key,
            timeout=10,
        )
        status_code = getattr(response, "status_code", 500)
        if status_code != 200:
            message = getattr(response, "message", "DashScope embedding 调用失败")
            raise RuntimeError(message)
        embeddings_data = response.output.get("embeddings", [])
        embeddings_data.sort(key=lambda item: item.get("text_index", 0))
        return [item["embedding"] for item in embeddings_data]

    def __call__(self, input: Documents) -> Embeddings:
        texts = [str(item) for item in input]
        if self._should_use_offline():
            if not self._warned_offline:
                logger.warning(
                    "Embedding API 未配置，使用本地确定性向量；仅适合开发和测试"
                )
                self._warned_offline = True
            return [_offline_embedding(text) for text in texts]
        try:
            return self._call_dashscope(texts)
        except Exception as error:
            logger.warning("DashScope Embedding 调用失败，降级本地向量: %s", error)
            return [_offline_embedding(text) for text in texts]


embeddings = DashScopeEmbeddingFunction()
