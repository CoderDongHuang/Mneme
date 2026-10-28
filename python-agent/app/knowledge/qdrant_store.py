"""Qdrant storage with Mneme's existing document/metadata/distance contract.

Point IDs are deterministic UUIDs; original IDs stay in payloads. No provider
models or remote code are loaded by the database or its client.
"""
from __future__ import annotations

import atexit
import math
import threading
import uuid
import os
from pathlib import Path

from qdrant_client import QdrantClient, models


class InvalidCollectionException(ValueError):
    pass


_clients: dict[str, QdrantClient] = {}
_client_lock = threading.Lock()


def _point_id(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mneme:point:" + value))


def _filter(where: dict | None) -> models.Filter | None:
    if not where:
        return None
    conditions = []
    for key, value in where.items():
        if key in {"$and", "$or"}:
            if not isinstance(value, list) or not value:
                raise ValueError("Logical filters require a nonempty list")
            nested = [_filter(item) for item in value]
            conditions.append(models.Filter(**{"must" if key == "$and" else "should": nested}))
            continue
        if key.startswith("$") or not key or any(char in key for char in '.[]"'):
            raise ValueError("Unsupported metadata filter field")
        field = f"metadata.{key}"
        operators = value if isinstance(value, dict) else {"$eq": value}
        for op, operand in operators.items():
            if op in {"$eq", "$ne"}:
                if isinstance(operand, float):
                    if not math.isfinite(operand):
                        raise ValueError("Numeric metadata filters must be finite")
                    condition = models.FieldCondition(key=field, range=models.Range(gte=operand, lte=operand))
                else:
                    condition = models.FieldCondition(key=field, match=models.MatchValue(value=operand))
                conditions.append(models.Filter(must_not=[condition]) if op == "$ne" else condition)
            elif op in {"$in", "$nin"}:
                if not isinstance(operand, list):
                    raise ValueError("Membership filters require a list")
                # An empty IN must never expand into an unrestricted query.
                if not operand:
                    condition = models.HasIdCondition(has_id=[])
                else:
                    condition = models.FieldCondition(key=field, match=models.MatchAny(any=operand))
                conditions.append(models.Filter(must_not=[condition]) if op == "$nin" else condition)
            elif op in {"$gt", "$gte", "$lt", "$lte"}:
                conditions.append(models.FieldCondition(key=field, range=models.Range(**{op[1:]: operand})))
            else:
                raise ValueError(f"Unsupported metadata filter operator: {op}")
    return models.Filter(must=conditions)


class VectorClient:
    def __init__(self, *, url: str | None = None, path: str | None = None, api_key: str = "", dimension: int = 1024, check_legacy: bool = False):
        if bool(url) == bool(path):
            raise ValueError("Specify exactly one Qdrant URL or local path")
        self.dimension = dimension
        if url:
            self.raw = QdrantClient(url=url, api_key=api_key or None, timeout=30)
        else:
            key = str(Path(path).resolve())
            with _client_lock:
                if key not in _clients:
                    Path(key).mkdir(parents=True, exist_ok=True)
                    _clients[key] = QdrantClient(path=key)
                    # Close SQLite handles before Python tears down imports.
                    atexit.register(_clients[key].close)
                self.raw = _clients[key]
        if check_legacy:
            legacy = Path(os.getenv("CHROMA_PATH", str(Path(__file__).resolve().parents[2] / "data" / "chroma")))
            if any((root / "chroma.sqlite3").exists() or any(root.glob("*/chroma.sqlite3")) for root in (legacy, Path("/data/chroma"))):
                if not self.raw.collection_exists("mneme_legacy_migration_receipt"):
                    raise RuntimeError("检测到旧 Chroma 数据；请先停写并运行 migrate_vector_store.py，不允许静默切换为空索引")

    def heartbeat(self):
        self.raw.get_collections()
        return True

    def list_collections(self):
        return [self.get_collection(item.name) for item in self.raw.get_collections().collections if item.name != "mneme_legacy_migration_receipt"]

    def get_collection(self, name, embedding_function=None):
        if not self.raw.collection_exists(name):
            raise InvalidCollectionException(name)
        return VectorCollection(self, name, embedding_function)

    def get_or_create_collection(self, name, metadata=None, embedding_function=None):
        if not self.raw.collection_exists(name):
            metric = (metadata or {}).get("hnsw:space", "l2")
            distance = {"l2": models.Distance.EUCLID, "cosine": models.Distance.COSINE, "ip": models.Distance.DOT}.get(metric)
            if distance is None:
                raise ValueError("Unsupported vector distance")
            try:
                self.raw.create_collection(name, vectors_config=models.VectorParams(size=self.dimension, distance=distance), metadata=metadata or {})
            except Exception:
                # Another agent may have created the same collection. Never mask
                # an outage or accept an incompatible vector space.
                if not self.raw.collection_exists(name):
                    raise
        collection = self.get_collection(name, embedding_function)
        config = self.raw.get_collection(name).config.params.vectors
        if not isinstance(config, models.VectorParams) or config.size != self.dimension:
            raise ValueError("Qdrant collection dimension mismatch")
        if metadata and "hnsw:space" in metadata:
            expected = {"l2": models.Distance.EUCLID, "cosine": models.Distance.COSINE, "ip": models.Distance.DOT}.get(metadata["hnsw:space"])
            if expected is None or config.distance != expected:
                raise ValueError("Qdrant collection distance mismatch")
        return collection

    def delete_collection(self, name):
        self.raw.delete_collection(name)


class VectorCollection:
    def __init__(self, client: VectorClient, name: str, embed=None):
        self.client, self.name, self.embed = client, name, embed

    @property
    def metadata(self):
        return self.client.raw.get_collection(self.name).config.metadata or {}

    def modify(self, *, metadata):
        self.client.raw.update_collection(self.name, metadata=metadata)

    def count(self):
        return self.client.raw.count(self.name, exact=True).count

    def get(self, ids=None, where=None, limit=None, offset=0, include=None):
        if limit is not None and limit < 0 or offset < 0:
            raise ValueError("Pagination must be nonnegative")
        include = ["documents", "metadatas"] if include is None else include
        query_filter = _filter(where)
        if ids is not None:
            id_filter = models.HasIdCondition(has_id=[_point_id(str(item)) for item in ids])
            query_filter = models.Filter(must=[id_filter] + ([query_filter] if query_filter else []))
        rows, cursor, skipped = [], None, 0
        while limit is None or len(rows) < limit:
            batch, cursor = self.client.raw.scroll(
                self.name, scroll_filter=query_filter, offset=cursor,
                limit=min(256, limit - len(rows) + max(0, offset - skipped)) if limit is not None else 256,
                with_payload=True, with_vectors="embeddings" in include,
            )
            for row in batch:
                if skipped < offset:
                    skipped += 1
                else:
                    rows.append(row)
            if cursor is None:
                break
        result = {"ids": [row.payload["id"] for row in rows]}
        for key, payload_key in (("documents", "document"), ("metadatas", "metadata")):
            if key in include:
                result[key] = [row.payload.get(payload_key) for row in rows]
        if "embeddings" in include:
            result["embeddings"] = [row.vector for row in rows]
        return result

    def _write(self, *, ids, documents=None, metadatas=None, embeddings=None, update=False, add=False):
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate point IDs")
        for values in (documents, metadatas, embeddings):
            if values is not None and len(values) != len(ids):
                raise ValueError("Point field count mismatch")
        if not ids:
            return
        current = {row.payload["id"]: row for row in self.client.raw.retrieve(self.name, [_point_id(str(item)) for item in ids], with_payload=True, with_vectors=True)}
        if add and current:
            raise ValueError("Point already exists")
        if embeddings is None and documents is not None:
            if self.embed is None:
                raise ValueError("Explicit embeddings or an embedding function required")
            embeddings = self.embed(documents)
        points = []
        for index, point_id in enumerate(ids):
            old = current.get(point_id)
            if update and old is None:
                continue
            payload = dict(old.payload) if old else {"id": point_id, "document": None, "metadata": None}
            if documents is not None:
                payload["document"] = documents[index]
            if metadatas is not None:
                payload["metadata"] = {**(payload.get("metadata") or {}), **metadatas[index]} if update else metadatas[index]
            vector = embeddings[index] if embeddings is not None else old.vector if old else None
            if vector is None:
                raise ValueError("New points require embeddings")
            points.append(models.PointStruct(id=_point_id(str(point_id)), vector=list(vector), payload=payload))
        if points:
            self.client.raw.upsert(self.name, points, wait=True)

    def add(self, **kwargs):
        self._write(**kwargs, add=True)

    def upsert(self, **kwargs):
        self._write(**kwargs)

    def update(self, **kwargs):
        self._write(**kwargs, update=True)

    def delete(self, ids=None, where=None):
        if ids is None and not where:
            raise ValueError("Deletion requires IDs or a filter")
        query_filter = _filter(where)
        if ids is not None:
            query_filter = models.Filter(must=[models.HasIdCondition(has_id=[_point_id(str(item)) for item in ids])] + ([query_filter] if query_filter else []))
        self.client.raw.delete(self.name, models.FilterSelector(filter=query_filter), wait=True)

    def query(self, query_texts=None, query_embeddings=None, n_results=10, where=None, include=None):
        if query_embeddings is None:
            if self.embed is None or query_texts is None:
                raise ValueError("Explicit query embeddings or an embedding function required")
            query_embeddings = self.embed(query_texts)
        include = ["documents", "metadatas", "distances"] if include is None else include
        result = {key: [] for key in ["ids", *include]}
        config = self.client.raw.get_collection(self.name).config.params.vectors
        requests = [models.QueryRequest(query=list(vector), filter=_filter(where), limit=max(1, n_results), with_payload=True, with_vector="embeddings" in include) for vector in query_embeddings]
        batches = self.client.raw.query_batch_points(self.name, requests) if requests and n_results > 0 else []
        for points in [batch.points for batch in batches] if batches else [[] for _ in query_embeddings]:
            result["ids"].append([point.payload["id"] for point in points])
            for key, payload_key in (("documents", "document"), ("metadatas", "metadata")):
                if key in include:
                    result[key].append([point.payload.get(payload_key) for point in points])
            if "distances" in include:
                result["distances"].append([point.score ** 2 if config.distance == models.Distance.EUCLID else 1 - point.score for point in points])
            if "embeddings" in include:
                result["embeddings"].append([point.vector for point in points])
        return result
