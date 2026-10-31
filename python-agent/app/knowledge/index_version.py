"""Content version shared by dense evidence and its FTS5 projection."""

import hashlib
import json
from typing import Any


def index_version(chunks: list[dict[str, Any]]) -> str:
    # Include every field stored in FTS5; normalize absent fields just as its writer does.
    rows = []
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        rows.append([
            str(chunk["id"]), str(chunk.get("content", "")),
            int(metadata.get("page", 0) or 0),
            *(str(metadata.get(key, default)) for key, default in (
                ("chunk_type", "text"), ("parser", ""), ("source", ""), ("section", ""))),
        ])
    rows.sort(key=lambda row: row[0])
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
