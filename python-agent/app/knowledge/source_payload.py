"""One citation wire format for JSON answers and SSE metadata."""
from math import isfinite

from app.models.chat import Source


def visual_region(value) -> list[float] | None:
    """Read both persisted CSV metadata and arrays; reject unusable rectangles."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        region = [float(item) for item in value]
    except (TypeError, ValueError, OverflowError):
        return None
    if any(isinstance(item, bool) for item in value) or not all(isfinite(item) for item in region):
        return None
    if not (0 <= region[0] <= region[2] <= 1 and 0 <= region[1] <= region[3] <= 1):
        return None
    return region


def citation_sources(chunks: list[dict]) -> list[Source]:
    # Keep every numbered passage, including an empty passage: removing it here
    # shifts [n] to the wrong document. Selection/numbering precedes this boundary.
    sources = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        sources.append(Source(
            retrieval_ranks=chunk.get("retrieval_ranks", {}),
            content_sha256=metadata.get("content_sha256", ""),
            indexed_at=metadata.get("indexed_at", ""),
            parser_version=metadata.get("parser_version", ""),
            document_id=str(metadata.get("document_id", "")),
            document_name=metadata.get("source", "未知文档"),
            chunk_content=chunk.get("content", ""),
            page=metadata.get("page") or None,
            section=metadata.get("section", ""),
            score=chunk.get("score", 0.0),
            chunk_type=metadata.get("chunk_type", "text"),
            evidence_type=metadata.get("evidence_type", "text"),
            visual_page=metadata.get("visual_page") or metadata.get("page") or None,
            visual_region=visual_region(metadata.get("visual_region")),
            ocr_confidence=metadata.get("ocr_confidence"),
        ))
    return sources
