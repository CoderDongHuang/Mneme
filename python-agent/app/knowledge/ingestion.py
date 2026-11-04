"""Document indexing orchestration after the independent parsing stage."""

import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from app.core.privacy import require_cloud_processing
from app.core.logging import setup_logger
from app.knowledge.chunking import chunk_documents
from app.knowledge.cancellation import check_cancelled
from app.knowledge.document_parser import (
    PARSER_VERSION,
    SUPPORTED_EXTENSIONS as SUPPORTED_EXTENSIONS,
    parse_document as parse_document,
)
from app.knowledge.lexical_index import lexical_index
from app.knowledge.index_version import index_version
from app.knowledge.index_reconciliation import synchronize_lexical
from app.knowledge.vector_store import vector_store
from app.knowledge.generations import generation_store, StaleGeneration
from app.utils.embedding import embeddings

logger = setup_logger("ingestion")


def ingest_document(
    user_id: str,
    kb_id: str,
    file_path: str,
    source_name: str | None = None,
    document_id: str | None = None,
    report: dict | None = None,
    index_generation: int | None = None,
) -> str:
    require_cloud_processing(user_id)
    # Gateway assigns this before parsing. Direct/legacy callers allocate locally
    # once their content-derived document ID is known below.
    generation = (generation_store.begin(user_id, kb_id, document_id, index_generation)
                  if document_id is not None else None)
    path = Path(file_path)
    source = source_name or path.name
    parsed = parse_document(file_path, source)
    check_cancelled()
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    indexed_at = datetime.now(timezone.utc).isoformat()
    warnings = [item.metadata["parse_warning"] for item in parsed if "parse_warning" in item.metadata]
    page_previews = {item.metadata["page_preview"]["page"]: item.metadata["page_preview"]
                     for item in parsed if "page_preview" in item.metadata}
    if report is not None:
        report.update({"parser_version": PARSER_VERSION, "content_sha256": content_hash,
                       "indexed_at": indexed_at, "warnings": warnings,
                       "status": "partial" if warnings else "done"})
    parsed = [item for item in parsed if item.page_content.strip()]
    chunks = chunk_documents(parsed)
    valid_chunks = [chunk for chunk in chunks if chunk.page_content.strip()]
    if report is not None:
        budget = 2_000_000
        for item in parsed:
            page = int(item.metadata.get("page") or 1)
            preview = page_previews.setdefault(page, {"page": page, "text": "", "ocr_regions": []})
            preview.setdefault("blocks", [])
            content = item.page_content[:max(0, budget)]
            budget -= len(content)
            preview["blocks"].append({"type": item.metadata.get("chunk_type", "text"),
                                      "section": item.metadata.get("section", ""), "content": content,
                                      "region": item.metadata.get("visual_region", "")})
            if not preview.get("text"):
                preview["text"] = content
        # Keep preview storage bounded; expose truncation rather than silently claiming completeness.
        truncated = budget <= 0
        text_budget = 2_000_000
        region_budget = 50_000
        for preview in page_previews.values():
            text = preview.get("text", "")
            regions = preview.get("ocr_regions", [])
            preview["text"] = text[:min(100_000, text_budget)]
            preview["ocr_regions"] = regions[:min(10000, region_budget)]
            preview["truncated"] = len(text) > len(preview["text"]) or len(regions) > len(preview["ocr_regions"])
            truncated = truncated or preview["truncated"]
            text_budget -= len(preview["text"])
            region_budget -= len(preview["ocr_regions"])
        report["pages"] = list(page_previews.values())
        report["page_count"] = len(page_previews)
        report["chunk_count"] = len(valid_chunks)
        report["preview_truncated"] = truncated
        report["chunks"] = [{"index": index, "page": chunk.metadata.get("page", 1),
                             "type": chunk.metadata.get("chunk_type", "text"),
                             "content": chunk.page_content[:4000]} for index, chunk in enumerate(valid_chunks[:500])]
        report["chunks_truncated"] = len(valid_chunks) > 500 or any(len(chunk.page_content) > 4000 for chunk in valid_chunks[:500])
    if not valid_chunks:
        raise ValueError("文档中没有可检索的文本；扫描件请启用 OCR 后重试")

    if document_id is None:
        digest = content_hash[:16]
        document_id = f"doc_{digest}"
    if generation is None:
        generation = generation_store.begin(user_id, kb_id, document_id, index_generation)

    ids = [f"{document_id}_g{generation}_{index:05d}" for index in range(len(valid_chunks))]
    metadatas = []
    for chunk in valid_chunks:
        metadata = {
            "document_id": document_id,
            "index_generation": generation,
            "source": source,
            "page": int(chunk.metadata.get("page", 0) or 0),
            "section": str(chunk.metadata.get("section", "")),
            "chunk_type": str(chunk.metadata.get("chunk_type", "text")),
            "evidence_type": str(
                chunk.metadata.get("evidence_type")
                or (
                    "visual"
                    if chunk.metadata.get("chunk_type") in {"image_vision", "table"}
                    else "text"
                )
            ),
            "visual_page": int(
                chunk.metadata.get("visual_page")
                or chunk.metadata.get("page", 0)
                or 0
            ),
            "visual_region": str(chunk.metadata.get("visual_region", "")),
            "parser": str(chunk.metadata.get("parser", "")),
            "parser_version": PARSER_VERSION,
            "content_sha256": content_hash,
            "indexed_at": indexed_at,
        }
        if chunk.metadata.get("ocr_confidence") is not None:
            metadata["ocr_confidence"] = float(chunk.metadata["ocr_confidence"])
        metadatas.append(metadata)
    check_cancelled()
    documents = [chunk.page_content for chunk in valid_chunks]
    indexed_chunks = [{"id": chunk_id, "content": content, "metadata": metadata}
                      for chunk_id, content, metadata in zip(ids, documents, metadatas)]
    version = index_version(indexed_chunks)
    for metadata in metadatas:
        metadata["index_version"] = version
    vectors = embeddings(documents)
    # Provider calls can outlast a lease. Confirm ownership after embedding and
    # before each persistent mutation, rather than inside Qdrant's callback.
    check_cancelled()
    # This transaction serializes generation publication and actual mutations.
    # A process paused after the lease check must acquire and recheck the durable
    # generation before writing. It cannot delete or replace a newer generation.
    with generation_store.writing(user_id, kb_id, document_id, generation):
        check_cancelled()
        collection = vector_store.get_or_create_collection(user_id, kb_id)
        old_ids = collection.get(where={"document_id": document_id}).get("ids", [])
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=vectors)
        check_cancelled()
        if report is not None:
            report.update({"index_generation": generation, "vector_index_version": version,
                           "lexical_index_version": None, "index_status": "pending"})
        try:
            index_report = synchronize_lexical(user_id, kb_id, document_id, indexed_chunks, index=lexical_index)
            if report is not None:
                report.update(index_report)
        except sqlite3.Error:
            if report is None:
                raise
            report.update({"status": "partial", "index_error": "lexical_index_pending"})
            logger.warning("document_index_pending operation=lexical_write")
        check_cancelled()
    # Commit publication before removing the previous readable generation.
    try:
        with generation_store.writing(user_id, kb_id, document_id, generation, repair=True):
            stale_ids = sorted(set(old_ids) - set(ids))
            if stale_ids:
                collection.delete(ids=stale_ids)
    except StaleGeneration:
        pass  # A newer writer/deletion owns cleanup; never touch its data.
    check_cancelled()
    logger.info(
        "文档入库完成: user=%s kb=%s document=%s source=%s chunks=%s",
        user_id,
        kb_id,
        document_id,
        source,
        len(valid_chunks),
    )
    return document_id
