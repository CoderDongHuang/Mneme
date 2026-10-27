"""Offline maintenance: dry-run, snapshot, rebuild, or restore one Chroma collection.

Run with services stopped and the same storage/environment as the agent. Snapshots
contain private source text and vectors; store them with your protected backups.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def snapshot(collection) -> dict:
    result = collection.get(include=["documents", "metadatas", "embeddings"])
    vectors = result["embeddings"]
    return {
        "schema_version": 1,
        "collection": collection.name,
        "metadata": collection.metadata,
        "ids": result["ids"],
        "documents": result["documents"],
        "metadatas": result["metadatas"],
        "embeddings": vectors.tolist() if hasattr(vectors, "tolist") else vectors,
    }


def restore(collection, data: dict) -> None:
    for start in range(0, len(data["ids"]), 64):
        end = start + 64
        kwargs = {key: data[key][start:end] for key in ("ids", "embeddings")}
        # Old collections may contain absent row metadata or text.
        for key in ("documents", "metadatas"):
            rows = data[key][start:end]
            if all(row is not None for row in rows):
                kwargs[key] = rows
        collection.update(**kwargs)
    collection.modify(metadata=data["metadata"] or {"description": "restored legacy collection"})


def rebuild(collection, embed, backup: Path) -> dict:
    data = snapshot(collection)
    if any(not text for text in data["documents"]):
        raise ValueError("Collection contains missing text; restore original files before rebuilding")
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    # Conservative allowance for a protected snapshot and temporary new vectors.
    if shutil.disk_usage(backup.parent).free < max(len(encoded) * 3, 16 * 1024 * 1024):
        raise ValueError("Insufficient free space for migration and rollback")
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    backup.with_suffix(backup.suffix + ".sha256").write_text(digest, encoding="ascii")
    # Finish ALL external embedding calls before touching the original collection.
    vectors = []
    for start in range(0, len(data["ids"]), 32):
        vectors.extend(embed(data["documents"][start:start + 32]))
    if len(vectors) != len(data["ids"]):
        raise ValueError("Embedding count mismatch; original collection unchanged")
    try:
        for start in range(0, len(data["ids"]), 64):
            collection.update(ids=data["ids"][start:start + 64], embeddings=vectors[start:start + 64])
        collection.modify(metadata={**(data["metadata"] or {}), "embedding_profile": embed.profile()})
    except Exception:
        restore(collection, data)
        raise
    return {"rows": len(vectors), "profile": embed.profile(), "snapshot_sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--apply", action="store_true", help="Default is read-only dry-run")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--backup", type=Path, help="New snapshot file; never overwrites")
    parser.add_argument("--restore", type=Path, help="Restore a previous snapshot (requires --apply)")
    args = parser.parse_args()
    if args.apply and not args.services_stopped:
        parser.error("Stop gateway/agents/workers first, then pass --services-stopped")
    from app.core.config import settings
    from app.utils.embedding import embeddings
    import chromadb
    from chromadb.config import Settings

    if settings.vector_shard_count > 1 or settings.vector_shard_urls:
        parser.error("For sharded stores, configure one shard endpoint per maintenance run")
    client = (chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                                 settings=Settings(anonymized_telemetry=False))
              if settings.chroma_mode == "http" else
              chromadb.PersistentClient(path=settings.chroma_path, settings=Settings(anonymized_telemetry=False)))
    collection = client.get_collection(args.collection, embedding_function=None)
    plan = {"collection": collection.name, "rows": collection.count(),
            "old_profile": (collection.metadata or {}).get("embedding_profile", "unknown"),
            "target_profile": embeddings.profile(), "mode": "apply" if args.apply else "dry-run"}
    print(json.dumps(plan))  # Never print text, metadata, vectors, or keys.
    if not args.apply:
        return
    if args.restore:
        encoded = args.restore.read_bytes()
        digest = args.restore.with_suffix(args.restore.suffix + ".sha256").read_text().strip()
        if hashlib.sha256(encoded).hexdigest() != digest:
            raise ValueError("Snapshot checksum mismatch")
        data = json.loads(encoded)
        if data.get("schema_version") != 1 or data["collection"] != collection.name:
            raise ValueError("Snapshot schema or collection mismatch")
        if set(collection.get(include=[])["ids"]) != set(data["ids"]):
            raise ValueError("Collection membership changed; restore the full system backup instead")
        restore(collection, data)
    else:
        if args.backup is None or not args.backup.parent.is_dir():
            parser.error("--backup must name a new file inside an existing protected backup directory")
        print(json.dumps(rebuild(collection, embeddings, args.backup)))


if __name__ == "__main__":
    main()
