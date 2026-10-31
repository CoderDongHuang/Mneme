"""Rebuild the derived lexical index without parsing files or invoking a provider."""

import sqlite3

from app.knowledge.cancellation import check_cancelled
from app.knowledge.index_version import index_version
from app.knowledge.lexical_index import lexical_index
from app.knowledge.vector_store import vector_store
from app.knowledge.filters import MetadataScope
from app.knowledge.generations import generation_store


def synchronize_lexical(user_id: str, kb_id: str, document_id: str, chunks: list[dict], *, index=lexical_index) -> dict:
    version = index_version(chunks)
    check_cancelled()
    index.replace_document(user_id, kb_id, document_id, chunks)
    persisted = index.document_version(user_id, kb_id, document_id)
    if persisted != version:
        raise sqlite3.DatabaseError("词法索引读回版本不匹配")
    check_cancelled()
    return {"vector_index_version": version, "lexical_index_version": persisted, "index_status": "ready"}


def reconcile_document(user_id: str, kb_id: str, document_id: str, expected_version: str) -> dict:
    state = generation_store.snapshot(user_id)
    doc = state.get("libraries", {}).get(str(kb_id), {}).get("documents", {}).get(str(document_id), {})
    generation = doc.get("active", 0)
    with generation_store.writing(user_id, kb_id, document_id, generation, repair=True):
        return {**_reconcile_document(user_id, kb_id, document_id, expected_version), "index_generation": generation}


def _reconcile_document(user_id: str, kb_id: str, document_id: str, expected_version: str) -> dict:
    # Provider profile changes do not prevent rebuilding an existing derived index.
    collection = vector_store.get_collection(user_id, kb_id, validate_profile=False)
    if collection is None:
        raise ValueError("向量索引不存在，请重新解析文档")
    collection = MetadataScope(collection, generation_store.where(user_id, kb_id))
    result = collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
    chunks = [
        {"id": chunk_id, "content": result["documents"][i], "metadata": result["metadatas"][i]}
        for i, chunk_id in enumerate(result.get("ids", []))
    ]
    if not chunks or index_version(chunks) != expected_version:
        raise ValueError("向量索引版本已变化，请刷新文档状态后重试")
    report = synchronize_lexical(user_id, kb_id, document_id, chunks)
    # Recheck actual rows as well as holding the generation fence.
    latest = collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
    current = [{"id": value, "content": latest["documents"][i], "metadata": latest["metadatas"][i]}
               for i, value in enumerate(latest.get("ids", []))]
    if index_version(current) != expected_version:
        raise ValueError("修复期间向量索引已变化，拒绝发布就绪状态")
    return {**report, "chunk_count": len(chunks)}
