import re
import hashlib
from pathlib import Path
from typing import Any

from app.knowledge.qdrant_store import VectorClient, InvalidCollectionException

from app.core.config import settings
from app.core.logging import setup_logger
from app.knowledge.lexical_index import lexical_index
from app.knowledge.generations import generation_store
from app.knowledge.filters import MetadataScope
from app.utils.embedding import embeddings


logger = setup_logger("vector_store")


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("_-")
    return (cleaned or "default")[:48]


def _get_collection_name(user_id: str, kb_id: str) -> str:
    shard = resolve_vector_shard(user_id, kb_id)
    suffix = "" if settings.vector_shard_count == 1 else f"_s{shard}"
    name = f"user_{_safe(user_id)}_kb_{_safe(kb_id)}{suffix}"
    if _safe(user_id) != user_id or _safe(kb_id) != kb_id:
        digest = hashlib.sha256(f"{len(user_id)}:{user_id}{kb_id}".encode()).hexdigest()[:16]
        name += f"_{digest}"
    return name[:120]


def resolve_vector_shard(user_id: str, kb_id: str) -> int:
    shard_count = max(1, settings.vector_shard_count)
    if shard_count == 1:
        return 0
    digest = hashlib.sha256(f"{user_id}:{kb_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % shard_count


class VectorStore:
    def __init__(self) -> None:
        self.clients = self._build_clients()
        self.client = self.clients[0]

    def _build_clients(self) -> list[Any]:
        urls = [item.strip() for item in settings.vector_shard_urls.split(",") if item.strip()]
        if urls:
            if settings.vector_shard_count not in {1, len(urls)}:
                raise ValueError("VECTOR_SHARD_COUNT 必须与 VECTOR_SHARD_URLS 数量一致")
            return [VectorClient(url=url, api_key=settings.qdrant_api_key, check_legacy=True) for url in urls]
        if settings.vector_store_mode == "http":
            return [VectorClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, check_legacy=True)]
        if settings.vector_store_mode != "local":
            raise ValueError("VECTOR_STORE_MODE must be local or http")
        count = max(1, settings.vector_shard_count)
        return [VectorClient(path=str(Path(settings.qdrant_path) / f"shard-{i}") if count > 1 else settings.qdrant_path, check_legacy=True) for i in range(count)]

    def _client_for(self, user_id: str, kb_id: str) -> Any:
        return self.clients[resolve_vector_shard(user_id, kb_id) % len(self.clients)]

    @staticmethod
    def _collection_name(item: Any) -> str:
        """Normalize Chroma 0.5 collection objects and 0.6 name objects."""
        return str(item) if type(item).__name__ == "CollectionName" else item.name

    @classmethod
    def _collections_for_client(cls, client: Any) -> list[Any]:
        collections = []
        for item in client.list_collections():
            if type(item).__name__ == "CollectionName" or isinstance(item, str):
                collections.append(client.get_collection(name=str(item)))
            else:
                collections.append(item)
        return collections

    def heartbeat(self) -> bool:
        for client in self.clients:
            client.heartbeat()
        return True

    def get_or_create_collection(self, user_id: str, kb_id: str) -> Any:
        collection = self.get_collection(user_id, kb_id)
        if collection is not None:
            return collection
        collection = self._client_for(user_id, kb_id).get_or_create_collection(
            name=_get_collection_name(user_id, kb_id),
            metadata={
                "user_id": user_id,
                "kb_id": kb_id,
                "vector_shard_id": resolve_vector_shard(user_id, kb_id),
                "vector_shard_count": settings.vector_shard_count,
                "embedding_profile": embeddings.profile(),
            },
            embedding_function=embeddings,
        )
        self._validate_collection(collection, user_id, kb_id)
        return collection

    @staticmethod
    def _validate_collection(collection: Any, user_id: str, kb_id: str, *, validate_profile: bool = True) -> None:
        metadata = collection.metadata or {}
        if str(metadata.get("user_id", "")) != str(user_id) or str(metadata.get("kb_id", "")) != str(kb_id):
            raise PermissionError("向量集合归属不匹配，操作已拒绝")
        if not validate_profile:
            return
        profile = metadata.get("embedding_profile")
        if profile != embeddings.profile():
            if collection.count():
                raise ValueError("Embedding 配置与索引不一致或旧索引缺少版本；请新建知识库并重新上传原文件")
            collection.modify(metadata={**metadata, "embedding_profile": embeddings.profile()})

    def get_collection(self, user_id: str, kb_id: str, *, validate_profile: bool = True) -> Any | None:
        try:
            collection = self._client_for(user_id, kb_id).get_collection(
                name=_get_collection_name(user_id, kb_id), embedding_function=embeddings
            )
        except InvalidCollectionException:
            return None
        self._validate_collection(collection, user_id, kb_id, validate_profile=validate_profile)
        return collection

    def delete_collection(self, user_id: str, kb_id: str) -> bool:
        generation_store.tombstone(user_id, kb_id)
        with generation_store.locked(user_id):
            return self._delete_collection(user_id, kb_id)

    def _delete_collection(self, user_id: str, kb_id: str) -> bool:
        for client, collection in self._deletion_collections(user_id, kb_id):
            client.delete_collection(name=collection.name)
        lexical_index.delete_collection(user_id, kb_id)
        self.require_deleted(user_id, kb_id)
        return True

    def delete_document(self, user_id: str, kb_id: str, document_id: str) -> int:
        generation_store.tombstone(user_id, kb_id, document_id)
        with generation_store.locked(user_id):
            return self._delete_document(user_id, kb_id, document_id)

    def cancel_document(self, user_id: str, kb_id: str, document_id: str) -> int:
        generation_store.suspend(user_id, kb_id, document_id)
        with generation_store.locked(user_id):
            return self._delete_document(user_id, kb_id, document_id)

    def _delete_document(self, user_id: str, kb_id: str, document_id: str) -> int:
        deleted = 0
        for _, collection in self._deletion_collections(user_id, kb_id):
            ids = collection.get(where={"document_id": document_id}).get("ids", [])
            if ids:
                collection.delete(ids=ids)
            deleted += len(ids)
        lexical_index.delete_document(user_id, kb_id, document_id)
        self.require_deleted(user_id, kb_id, document_id)
        return deleted

    def _deletion_collections(self, user_id: str, kb_id: str) -> list[tuple[Any, Any]]:
        """Inspect all configured shards, including collections from an old resolver.

        The current name still undergoes the strict ownership check. Other
        names are included only when both tenant and KB metadata match.
        Embedding profile changes must not prevent erasure.
        """
        current = self.get_collection(user_id, kb_id, validate_profile=False)
        found = [] if current is None else [(self._client_for(user_id, kb_id), current)]
        seen = {(id(client), collection.name) for client, collection in found}
        for client in self.clients:
            for collection in self._collections_for_client(client):
                metadata = collection.metadata or {}
                identity = (id(client), collection.name)
                if identity not in seen and str(metadata.get("user_id", "")) == str(user_id) and str(metadata.get("kb_id", "")) == str(kb_id):
                    found.append((client, collection))
                    seen.add(identity)
        return found

    def deletion_report(self, user_id: str, kb_id: str | None = None, document_id: str | None = None) -> dict[str, int]:
        """Counts are independently read; -1 means unverified, never zero."""
        if document_id is not None and kb_id is None:
            raise ValueError("document_id requires kb_id")
        report = {"qdrant_chunks": -1, "fts_rows": -1}
        if document_id is None:
            report["qdrant_collections"] = -1
        try:
            collections = self.list_user_collections(user_id) if kb_id is None else [
                collection for _, collection in self._deletion_collections(user_id, kb_id)
            ]
            report["qdrant_chunks"] = sum(
                len(collection.get(where={"document_id": document_id})["ids"])
                if document_id is not None else collection.count() for collection in collections
            )
            if document_id is None:
                report["qdrant_collections"] = len(collections)
        except Exception as error:
            logger.warning("deletion_readback_failed store=qdrant error_type=%s", type(error).__name__)
        try:
            report["fts_rows"] = lexical_index.count_scope(user_id, kb_id, document_id)
        except Exception as error:
            logger.warning("deletion_readback_failed store=fts error_type=%s", type(error).__name__)
        return report

    def require_deleted(self, user_id: str, kb_id: str | None = None, document_id: str | None = None) -> None:
        report = self.deletion_report(user_id, kb_id, document_id)
        if any(count != 0 for count in report.values()):
            raise RuntimeError("deletion verification failed: " + str(report))

    def get_document_chunks(
        self, user_id: str, kb_id: str, document_id: str
    ) -> list[dict[str, Any]]:
        collection = self.get_collection(user_id, kb_id)
        if collection is None:
            return []
        result = MetadataScope(collection, generation_store.where(user_id, kb_id)).get(
            where={"document_id": document_id},
            include=["documents", "metadatas"],
        )
        chunks = []
        for index, chunk_id in enumerate(result.get("ids", [])):
            chunks.append(
                {
                    "id": chunk_id,
                    "content": (result.get("documents") or [""])[index],
                    "metadata": (result.get("metadatas") or [{}])[index] or {},
                }
            )
        return chunks

    def list_user_collections(self, user_id: str) -> list[Any]:
        collections = [
            collection
            for client in self.clients
            for collection in self._collections_for_client(client)
        ]
        return [
            collection
            for collection in collections
            if str((collection.metadata or {}).get("user_id", "")) == str(user_id)
        ]

    def get_collection_stats(self, user_id: str) -> list[dict[str, Any]]:
        stats = []
        for collection in self.list_user_collections(user_id):
            metadata = collection.metadata or {}
            stats.append(
                {
                    "name": collection.name,
                    "kb_id": metadata.get("kb_id", collection.name.split("_kb_")[-1]),
                    "vector_shard_id": metadata.get("vector_shard_id", 0),
                    "vector_shard_count": metadata.get("vector_shard_count", 1),
                    "chunk_count": MetadataScope(collection, generation_store.where(user_id, str(metadata.get("kb_id", "")))).count(),
                    "metadata": metadata,
                }
            )
        return stats

    def get_total_stats(self) -> dict[str, Any]:
        by_shard = []
        collections = []
        for shard_id, client in enumerate(self.clients):
            shard_collections = self._collections_for_client(client)
            collections.extend(shard_collections)
            by_shard.append({
                "shard_id": shard_id,
                "collections": len(shard_collections),
                "chunks": sum(collection.count() for collection in shard_collections),
            })
        return {
            "total_collections": len(collections),
            "total_chunks": sum(collection.count() for collection in collections),
            "collection_names": [self._collection_name(collection) for collection in collections],
            "vector_shard_id": settings.vector_shard_id,
            "vector_shard_count": settings.vector_shard_count,
            "active_shard_clients": len(self.clients),
            "shards": by_shard,
        }

    def delete_user_collections(self, user_id: str) -> int:
        generation_store.tombstone(user_id)
        with generation_store.locked(user_id):
            return self._delete_user_collections(user_id)

    def _delete_user_collections(self, user_id: str) -> int:
        deleted = 0
        for client in self.clients:
            for collection in self._collections_for_client(client):
                metadata = collection.metadata or {}
                if str(metadata.get("user_id", "")) == str(user_id):
                    deleted += collection.count()
                    client.delete_collection(collection.name)
        lexical_index.delete_user(user_id)
        self.require_deleted(user_id)
        return deleted

    def cleanup_orphan_collections(
        self, valid_kb_pairs: set[tuple[str, str]]
    ) -> dict[str, Any]:
        removed: list[str] = []
        kept: list[str] = []
        errors: list[dict[str, str]] = []
        for client in self.clients:
            for collection in self._collections_for_client(client):
                metadata = collection.metadata or {}
                user_id = str(metadata.get("user_id", ""))
                kb_id = str(metadata.get("kb_id", ""))
                if not user_id or not kb_id:
                    continue
                if (user_id, kb_id) in valid_kb_pairs:
                    kept.append(collection.name)
                    continue
                try:
                    client.delete_collection(collection.name)
                    removed.append(collection.name)
                except Exception as error:
                    errors.append({"name": collection.name, "error": str(error)})
        return {"removed": removed, "kept": kept, "errors": errors}


vector_store = VectorStore()
