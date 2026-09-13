import math
import re
from collections import Counter

from app.core.config import settings
from app.core.logging import setup_logger
from app.knowledge.vector_store import vector_store

logger = setup_logger("retriever")
RRF_K = 60
MAX_LEXICAL_DOCUMENTS = 1000


def _terms(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    terms = re.findall(r"[a-z0-9_+-]{2,}", normalized)
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        terms.extend(run[index : index + 2] for index in range(len(run) - 1))
        if len(run) == 1:
            terms.append(run)
    return terms


def rewrite_queries(query: str) -> list[str]:
    """Create deterministic search variants without requiring another LLM call."""
    normalized = re.sub(r"\s+", " ", query).strip()
    stripped = re.sub(
        r"^(请|麻烦|帮我|能否|可以)?(根据资料|结合文档|告诉我|解释一下|分析一下)",
        "",
        normalized,
    ).strip(" ，。！？?")
    variants = [normalized]
    if stripped and stripped != normalized:
        variants.append(stripped)
    keywords = " ".join(dict.fromkeys(_terms(stripped or normalized)))
    if keywords and keywords not in variants:
        variants.append(keywords)
    return variants[:3]


def _bm25_candidates(collection, query: str, limit: int) -> list[dict]:
    try:
        results = collection.get(
            limit=MAX_LEXICAL_DOCUMENTS, include=["documents", "metadatas"]
        )
    except Exception as error:
        logger.warning("BM25 降级检索失败: %s", error)
        return []
    documents = results.get("documents", [])
    tokenized = [_terms(content or "") for content in documents]
    query_terms = list(dict.fromkeys(_terms(query)))
    if not query_terms or not tokenized:
        return []
    average_length = sum(map(len, tokenized)) / max(1, len(tokenized))
    document_frequency = Counter(
        term for terms in tokenized for term in set(terms) if term in query_terms
    )
    candidates = []
    for index, terms in enumerate(tokenized):
        frequencies = Counter(terms)
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if not frequency:
                continue
            frequency_docs = document_frequency[term]
            inverse_frequency = math.log(
                1 + (len(tokenized) - frequency_docs + 0.5) / (frequency_docs + 0.5)
            )
            denominator = frequency + 1.5 * (
                0.25 + 0.75 * len(terms) / max(1.0, average_length)
            )
            score += inverse_frequency * frequency * 2.5 / denominator
        if score > 0:
            candidates.append(
                {
                    "id": results.get("ids", [])[index],
                    "content": documents[index],
                    "metadata": results.get("metadatas", [])[index] or {},
                    "lexical_score": score,
                }
            )
    candidates.sort(key=lambda item: item["lexical_score"], reverse=True)
    return candidates[:limit]


def _semantic_candidates(collection, queries: list[str], limit: int) -> list[dict]:
    candidates = []
    for query_index, query in enumerate(queries):
        results = collection.query(
            query_texts=[query], n_results=min(limit, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        for index, chunk_id in enumerate(results.get("ids", [[]])[0]):
            candidates.append(
                {
                    "id": chunk_id,
                    "content": results.get("documents", [[]])[0][index],
                    "metadata": results.get("metadatas", [[]])[0][index] or {},
                    "distance": float(results.get("distances", [[]])[0][index]),
                    "query_index": query_index,
                }
            )
    return candidates


def _deduplicate(ranked: list[dict], limit: int) -> list[dict]:
    selected = []
    fingerprints: set[tuple[str, str]] = set()
    for item in ranked:
        metadata = item.get("metadata", {})
        content_key = re.sub(r"\s+", "", item.get("content", ""))[:160]
        location = f"{metadata.get('document_id', metadata.get('source', ''))}:{metadata.get('page', '')}"
        fingerprint = (location, content_key)
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def retrieve(user_id: str, kb_id: str, query: str, top_k: int | None = None) -> list[dict]:
    limit = max(1, min(top_k or settings.retriever_top_k, 20))
    collection = vector_store.get_collection(user_id, kb_id)
    if collection is None or collection.count() == 0 or not query.strip():
        return []
    pool_size = min(max(limit * 4, 20), collection.count())
    ranked_lists: list[list[dict]] = []
    try:
        semantic = _semantic_candidates(collection, rewrite_queries(query), pool_size)
        by_query: dict[int, list[dict]] = {}
        for item in semantic:
            by_query.setdefault(item.pop("query_index"), []).append(item)
        ranked_lists.extend(by_query.values())
    except Exception as error:
        logger.warning(
            "语义检索失败，使用 BM25 降级: user=%s kb=%s error=%s",
            user_id, kb_id, error,
        )
    lexical = _bm25_candidates(collection, query, pool_size)
    if lexical:
        ranked_lists.append(lexical)
    merged: dict[str, dict] = {}
    for result_list in ranked_lists:
        for rank, item in enumerate(result_list, start=1):
            current = merged.setdefault(item["id"], {**item, "score": 0.0})
            current["score"] += 1.0 / (RRF_K + rank)
            if "distance" in item:
                current["distance"] = min(item["distance"], current.get("distance", item["distance"]))
            if "lexical_score" in item:
                current["lexical_score"] = item["lexical_score"]
    ranked = sorted(merged.values(), key=lambda item: item["score"], reverse=True)
    return _deduplicate(ranked, limit)
