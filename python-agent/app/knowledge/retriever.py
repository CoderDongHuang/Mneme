import math
import re
from collections import Counter
from functools import lru_cache

import jieba.posseg

from app.core.config import settings
from app.core.privacy import require_cloud_processing
from app.core.logging import setup_logger
from app.core.telemetry import tracer
from app.knowledge.lexical_index import lexical_index
from app.knowledge.filters import DocumentScope
from app.knowledge.reranker import rerank
from app.knowledge.vector_store import vector_store
from app.utils.embedding import embeddings

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
    candidates.sort(
        key=lambda item: (-item["lexical_score"], str(item.get("id", "")))
    )
    return candidates[:limit]


def _indexed_candidates(
    user_id: str, kb_id: str, query: str, limit: int, document_ids: list[str] | None = None
) -> list[dict]:
    if document_ids is None:
        return lexical_index.search(user_id, kb_id, query, limit)
    return lexical_index.search(user_id, kb_id, query, limit, document_ids=document_ids)


def _exact_semantic_candidates(
    collection, queries: list[str], limit: int
) -> list[dict]:
    results = collection.get(include=["documents", "metadatas", "embeddings"])
    chunk_ids = results.get("ids", [])
    documents = results.get("documents", [])
    metadatas = results.get("metadatas", [])
    stored_embeddings = results.get("embeddings")
    if stored_embeddings is None or len(stored_embeddings) != len(chunk_ids):
        return []
    candidates = []
    for query_index, query_embedding in enumerate(embeddings(queries)):
        query_candidates = []
        for index, chunk_id in enumerate(chunk_ids):
            stored_embedding = stored_embeddings[index]
            distance = sum(
                (float(left) - float(right)) ** 2
                for left, right in zip(query_embedding, stored_embedding)
            )
            query_candidates.append(
                {
                    "id": chunk_id,
                    "content": documents[index],
                    "metadata": metadatas[index] or {},
                    "distance": distance,
                    "query_index": query_index,
                }
            )
        query_candidates.sort(key=lambda item: (item["distance"], str(item["id"])))
        candidates.extend(query_candidates[:limit])
    return candidates


def _semantic_candidates(collection, queries: list[str], limit: int) -> list[dict]:
    if settings.offline_embeddings:
        return _exact_semantic_candidates(collection, queries, limit)
    return _ann_semantic_candidates(collection, queries, limit)


def _ann_semantic_candidates(collection, queries: list[str], limit: int) -> list[dict]:
    if not queries:
        return []
    # Send all rewrites in one embedding request and one vector-store query.
    # Sequential query_texts calls paid the provider round trip for every rewrite.
    results = collection.query(
        query_embeddings=embeddings(queries), n_results=min(limit, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    candidates = []
    for query_index in range(len(queries)):
        query_candidates = []
        for index, chunk_id in enumerate(results["ids"][query_index]):
            query_candidates.append(
                {
                    "id": chunk_id,
                    "content": results["documents"][query_index][index],
                    "metadata": results["metadatas"][query_index][index] or {},
                    "distance": float(results["distances"][query_index][index]),
                    "query_index": query_index,
                }
            )
        query_candidates.sort(key=lambda item: (item["distance"], str(item["id"])))
        candidates.extend(query_candidates)
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


def _term_coverage(query: str, item: dict) -> float:
    query_terms = set(_terms(query))
    if not query_terms:
        return 0.0
    metadata = item.get("metadata", {})
    searchable = " ".join(
        (
            str(item.get("content", "")),
            str(metadata.get("source", "")),
            str(metadata.get("section", "")),
        )
    )
    content_terms = set(_terms(searchable))
    return len(query_terms & content_terms) / len(query_terms)


_ABSTRACT_NOUNS = frozenset({
    "内容", "资料", "文档", "文件", "项目", "计划", "目标", "定义", "名称", "英文名称",
    "字段", "信息", "结构", "方式", "方法", "方案", "情况", "原因", "问题", "作用",
    "关系", "含义", "意义", "结果", "零点", "主题", "功能", "系统", "模型",
    "目标值", "指标", "答案", "证据", "能力", "记录",
})

# Bounded lexical equivalents, not a semantic entailment model. Keep the
# original term too; answer-level verification remains mandatory.
_FOCUS_EQUIVALENTS = {
    "售价": ("价格", "定价", "售价"),
    "价格": ("价格", "定价", "售价"),
    "作者": ("作者", "撰写", "著者", "编写"),
    "地点": ("地点", "地址", "位于", "举行", "举办"),
    "续航": ("续航", "连续工作", "持续运行", "使用时长"),
    "时间": ("时间", "日期", "时刻", "小时", "分钟", "天", "周", "月", "年"),
}


@lru_cache(maxsize=512)
def _question_focus(query: str) -> tuple[str, ...]:
    """Concrete nouns in explicit field/containment questions, not answer labels.

    Open semantic questions and abstract relations are left to hybrid retrieval.
    Negated verbs are deliberately not treated as evidence requirements.
    """
    if not re.search(r"的|是否|有没有", query):
        return ()
    query = re.sub(r"(?:资料|文档|文件)中", " ", query)
    return tuple(dict.fromkeys(
        token.word for token in jieba.posseg.cut(query)
        if token.flag.startswith("n") and len(token.word) >= 2 and token.word not in _ABSTRACT_NOUNS
    ))


def _supported_candidates(query: str, candidates: list[dict]) -> list[dict]:
    if not settings.retriever_focus_gate_enabled:
        return candidates
    terms = _question_focus(query)
    if not terms:
        return candidates
    supported = []
    for item in candidates:
        # Filenames and headings may mention the topic but are not answer evidence.
        content = str(item.get("content", "")).casefold()
        coverage = sum(
            any(alias.casefold() in content for alias in _FOCUS_EQUIVALENTS.get(term, (term,)))
            for term in terms
        ) / len(terms)
        if coverage == 1:
            supported.append({**item, "focus_coverage": coverage})
    return supported


def _retrieve(user_id: str, kb_id: str, query: str, top_k: int | None = None, document_ids: list[str] | None = None) -> list[dict]:
    limit = max(1, min(top_k or settings.retriever_top_k, 20))
    collection = vector_store.get_collection(user_id, kb_id)
    if document_ids is not None:
        if not document_ids or collection is None:
            return []
        collection = DocumentScope(collection, document_ids)
    if collection is None or collection.count() == 0 or not query.strip():
        return []
    pool_size = min(max(limit * 4, 20), collection.count())
    ranked_lists: list[tuple[str, list[dict]]] = []
    try:
        queries = rewrite_queries(query) if settings.retriever_rewrite_enabled else [query]
        semantic = _semantic_candidates(collection, queries, pool_size)
        by_query: dict[int, list[dict]] = {}
        for item in semantic:
            by_query.setdefault(item.pop("query_index"), []).append(item)
        ranked_lists.extend((f"dense:{index}", items) for index, items in by_query.items())
    except Exception as error:
        logger.warning(
            "语义检索失败，使用 BM25 降级: user=%s kb=%s error=%s",
            user_id, kb_id, error,
        )
    lexical = (_indexed_candidates(user_id, kb_id, query, pool_size) if document_ids is None
               else _indexed_candidates(user_id, kb_id, query, pool_size, document_ids))
    if lexical:
        # SQLite is a derived index. Never trust stale content or incomplete metadata.
        canonical = collection.get(ids=[item["id"] for item in lexical], include=["documents", "metadatas"])
        live = {
            chunk_id: {"content": content, "metadata": metadata or {}}
            for chunk_id, content, metadata in zip(
                canonical.get("ids", []), canonical.get("documents", []), canonical.get("metadatas", [])
            )
        }
        lexical = [{**item, **live[item["id"]]} for item in lexical if item["id"] in live]
    if not lexical:
        lexical = _bm25_candidates(collection, query, pool_size)
    if lexical:
        ranked_lists.append(("bm25", lexical))
    merged: dict[str, dict] = {}
    for channel, result_list in ranked_lists:
        for rank, item in enumerate(result_list, start=1):
            current = merged.setdefault(item["id"], {**item, "score": 0.0, "retrieval_ranks": {}})
            current["score"] += 1.0 / (RRF_K + rank)
            current["retrieval_ranks"][channel] = rank
            if "distance" in item:
                current["distance"] = min(item["distance"], current.get("distance", item["distance"]))
            if "lexical_score" in item:
                current["lexical_score"] = item["lexical_score"]
    for item in merged.values():
        item["term_coverage"] = _term_coverage(query, item)
        item["score"] += item["term_coverage"] / RRF_K
    ranked = sorted(
        merged.values(),
        key=lambda item: (
            -item["score"],
            -item.get("lexical_score", 0.0),
            item.get("distance", math.inf),
            str(item["id"]),
        ),
    )
    candidates = _supported_candidates(query, _deduplicate(ranked, pool_size))
    return rerank(query, candidates, limit)


def retrieve(user_id: str, kb_id: str, query: str, top_k: int | None = None, document_ids: list[str] | None = None) -> list[dict]:
    require_cloud_processing(user_id)
    with tracer.start_as_current_span("mneme.retrieval") as span:
        span.set_attribute("mneme.knowledge_base_id", kb_id)
        span.set_attribute("mneme.retrieval.top_k", top_k or settings.retriever_top_k)
        results = _retrieve(user_id, kb_id, query, top_k, document_ids)
        span.set_attribute("mneme.retrieval.result_count", len(results))
        return results
