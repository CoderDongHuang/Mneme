"""Export a stopped legacy Chroma store, then import and verify it in Qdrant.

The exporter uses only the legacy HTTP API (no Chroma package installation).
Snapshots contain private text/vectors: keep them in encrypted backup storage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
RECEIPT = "mneme_legacy_migration_receipt"


def _request(base, path, data=None):
    request = Request(base.rstrip("/") + "/api/v2/tenants/default_tenant/databases/default_database/" + path,
                      data=json.dumps(data).encode() if data is not None else None,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def export_legacy(url: str, output: Path):
    if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
        raise ValueError("Snapshot files must be new")
    collections, offset = [], 0
    while True:
        page = _request(url, f"collections?limit=100&offset={offset}")
        collections.extend(page)
        if len(page) < 100:
            break
        offset += len(page)
    snapshots = []
    for collection in collections:
        name, ident = collection["name"], collection["id"]
        count = _request(url, f"collections/{ident}/count")
        rows = {key: [] for key in ("ids", "documents", "metadatas", "embeddings")}
        for offset in range(0, count, 256):
            batch = _request(url, f"collections/{ident}/get", {"limit": 256, "offset": offset, "include": ["documents", "metadatas", "embeddings"]})
            for key in rows:
                rows[key].extend(batch[key])
        if len(rows["ids"]) != count or _request(url, f"collections/{ident}/count") != count:
            raise ValueError("Legacy store changed during export; stop all writers")
        snapshots.append({"collection": name, "metadata": collection.get("metadata") or {}, **rows})
    encoded = json.dumps({"schema_version": 1, "source": "chroma", "collections": snapshots}, ensure_ascii=False).encode()
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
    output.with_suffix(output.suffix + ".sha256").write_text(hashlib.sha256(encoded).hexdigest(), encoding="ascii")
    return {"collections": len(snapshots), "points": sum(len(item["ids"]) for item in snapshots)}


def read_snapshot(path: Path):
    encoded = path.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != path.with_suffix(path.suffix + ".sha256").read_text().strip():
        raise ValueError("Snapshot checksum mismatch")
    data = json.loads(encoded)
    if data.get("schema_version") != 1 or data.get("source") != "chroma":
        raise ValueError("Unsupported snapshot schema")
    names = set()
    for item in data["collections"]:
        name = item["collection"]
        if name in names or name == RECEIPT:
            raise ValueError("Duplicate/reserved collection name")
        names.add(name)
        size = len(item["ids"])
        if len(set(item["ids"])) != size or any(len(item[key]) != size for key in ("documents", "metadatas", "embeddings")):
            raise ValueError("Invalid snapshot row membership")
        dimensions = {len(vector) for vector in item["embeddings"]}
        if len(dimensions) > 1 or 0 in dimensions or any(not math.isfinite(value) for vector in item["embeddings"] for value in vector):
            raise ValueError("Invalid snapshot vectors")
    return data, digest


def import_snapshot(client, data, digest):
    """Require a fresh target, validate every payload/vector, roll back on failure."""
    if client.raw.get_collections().collections:
        raise ValueError("Target must be empty; preserve it and choose a new target")
    created = []
    try:
        for item in data["collections"]:
            name = item["collection"]
            if item["embeddings"] and len(item["embeddings"][0]) != client.dimension:
                raise ValueError("Target embedding dimension mismatch")
            collection = client.get_or_create_collection(name, metadata=item["metadata"])
            created.append(name)
            for offset in range(0, len(item["ids"]), 64):
                rows = {key: item[key][offset:offset + 64] for key in ("ids", "embeddings")}
                # Preserve nulls too; legacy rows may lack text or metadata.
                from qdrant_client import models
                from app.knowledge.qdrant_store import _point_id
                points = [models.PointStruct(id=_point_id(ident), vector=vector, payload={"id": ident, "document": doc, "metadata": meta})
                          for ident, vector, doc, meta in zip(rows["ids"], rows["embeddings"], item["documents"][offset:offset+64], item["metadatas"][offset:offset+64])]
                client.raw.upsert(name, points, wait=True)
            actual = collection.get(include=["documents", "metadatas", "embeddings"])
            expected_rows = {ident: (doc, meta, vector) for ident, doc, meta, vector in zip(item["ids"], item["documents"], item["metadatas"], item["embeddings"])}
            if collection.count() != len(expected_rows) or set(actual["ids"]) != set(expected_rows) or collection.metadata != item["metadata"]:
                raise ValueError("Migrated collection membership/metadata mismatch")
            for index, ident in enumerate(actual["ids"]):
                doc, meta, vector = expected_rows[ident]
                if actual["documents"][index] != doc or actual["metadatas"][index] != meta or len(actual["embeddings"][index]) != len(vector) or not all(math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-7) for a, b in zip(actual["embeddings"][index], vector)):
                    raise ValueError("Migrated payload/vector mismatch")
        client.get_or_create_collection(RECEIPT, metadata={"snapshot_sha256": digest, "collections": len(created)})
        created.append(RECEIPT)
    except Exception:
        for name in reversed(created):
            client.delete_collection(name)
        raise
    return {"verified_collections": len(data["collections"]), "snapshot_sha256": digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--source-url", default="http://chroma:8000")
    parser.add_argument("--target-url")
    parser.add_argument("--target-path")
    parser.add_argument("--dimension", type=int, default=1024)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    args = parser.parse_args()
    if not args.services_stopped:
        parser.error("Stop gateways, agents and workers first; pass --services-stopped")
    if args.action == "export":
        print(json.dumps(export_legacy(args.source_url, args.snapshot)))
    else:
        data, digest = read_snapshot(args.snapshot)
        if not args.apply:
            print(json.dumps({"dry_run": True, "collections": len(data["collections"]), "snapshot_sha256": digest}))
            return
        from app.knowledge.qdrant_store import VectorClient
        client = VectorClient(url=args.target_url, path=args.target_path, api_key=os.getenv("QDRANT_API_KEY", ""), dimension=args.dimension)
        print(json.dumps(import_snapshot(client, data, digest)))


if __name__ == "__main__":
    main()
