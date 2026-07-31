import re

from app.core.config import settings
from app.core.logging import setup_logger
from app.knowledge.vector_store import vector_store


logger = setup_logger("retriever")


def _terms(text: str) -> set[str]:
    normalized = text.lower()
    words = set(re.findall(r"[a-z0-9_+-]{2,}", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    words.update(
        chinese[index : index + 2] for index in range(max(0, len(chinese) - 1))
    )
    return {term for term in words if term}


def _keyword_candidates(collection, query: str, limit: int) -> list[dict]:
    try:
        results = collection.get(limit=200, include=["documents", "metadatas"])
    except Exception as error:
        logger.warning("关键词降级检索失败: %s", error)
        return []
    query_terms = _terms(query)
    candidates = []
    for index, chunk_id in enumerate(results.get("ids", [])):
        content = results.get("documents", [])[index]
        metadata = results.get("metadatas", [])[index] or {}
        content_terms = _terms(content)
        lexical = len(query_terms & content_terms) / max(1, len(query_terms))
        candidates.append(
            {
                "id": chunk_id,
                "content": content,
                "metadata": metadata,
                "score": lexical,
                "distance": 1.0 - lexical,
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:limit]


def retrieve(
    user_id: str, kb_id: str, query: str, top_k: int | None = None
) -> list[dict]:
    limit = max(1, min(top_k or settings.retriever_top_k, 20))
    collection = vector_store.get_collection(user_id, kb_id)
    if collection is None or collection.count() == 0:
        return []

    semantic: list[dict] = []
    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(limit, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for index, chunk_id in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 1.0
            semantic.append(
                {
                    "id": chunk_id,
                    "content": documents[index],
                    "metadata": metadatas[index] or {},
                    "score": 1.0 / (1.0 + max(distance, 0.0)),
                    "distance": distance,
                }
            )
    except Exception as error:
        logger.warning(
            "语义检索失败，使用关键词降级: user=%s kb=%s error=%s",
            user_id,
            kb_id,
            error,
        )

    keyword = _keyword_candidates(collection, query, limit)
    merged = {item["id"]: item for item in semantic}
    for item in keyword:
        if item["id"] in merged:
            merged[item["id"]]["score"] = min(
                1.0, merged[item["id"]]["score"] * 0.75 + item["score"] * 0.25
            )
        else:
            merged[item["id"]] = item
    ranked = list(merged.values())
    ranked.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return ranked[:limit]
