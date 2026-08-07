import re
from typing import Iterable

from langchain_core.documents import Document


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 160
_HEADING_PATTERN = re.compile(
    r"^(#{1,6}\s+.+|第[一二三四五六七八九十百0-9]+[章节部分].*|\d+(?:\.\d+)*[、.\s].+)$"
)


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + chunk_size)
                chunks.append(paragraph[start:end].strip())
                if end == len(paragraph):
                    break
                start = max(start + 1, end - overlap)
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            chunks.append(current)
            prefix = current[-overlap:].strip() if overlap else ""
            current = f"{prefix}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def chunk_documents(
    documents: Iterable[Document],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Document]:
    """Structure-aware splitter that preserves source, page, section and type."""
    output: list[Document] = []
    current_section = ""
    for document in documents:
        metadata = dict(document.metadata or {})
        content = document.page_content.strip()
        if not content:
            continue
        chunk_type = metadata.get("chunk_type", "text")
        if chunk_type == "title" or _HEADING_PATTERN.match(content.splitlines()[0]):
            current_section = content.splitlines()[0][:200]
            metadata["section"] = current_section
        elif current_section and not metadata.get("section"):
            metadata["section"] = current_section

        pieces = (
            [content]
            if chunk_type in {"table", "title", "image_ocr", "image_vision"}
            else _split_text(content, chunk_size, overlap)
        )
        for index, piece in enumerate(pieces):
            chunk_metadata = dict(metadata)
            chunk_metadata["chunk_index"] = index
            output.append(Document(page_content=piece, metadata=chunk_metadata))
    return output
