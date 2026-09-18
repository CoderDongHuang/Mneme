from __future__ import annotations


def select_citations(chunks: list[dict], max_citations: int = 3) -> list[dict]:
    """Return the final evidence locations shown to the user.

    Retrieval candidates are context for generation, not citations by themselves. Keep
    the strongest document and include adjacent chunks from that document only.
    """
    if not chunks or max_citations <= 0:
        return []
    primary = chunks[0]
    metadata = primary.get("metadata", {})
    document_id = str(metadata.get("document_id") or metadata.get("source") or "")
    selected = [primary]
    seen = {str(primary.get("id", ""))}
    for chunk in chunks[1:]:
        chunk_metadata = chunk.get("metadata", {})
        chunk_document_id = str(
            chunk_metadata.get("document_id") or chunk_metadata.get("source") or ""
        )
        chunk_id = str(chunk.get("id", ""))
        if chunk_document_id != document_id or chunk_id in seen:
            continue
        selected.append(chunk)
        seen.add(chunk_id)
        if len(selected) >= max_citations:
            break
    return selected
