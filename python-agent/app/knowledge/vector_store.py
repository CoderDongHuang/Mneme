import os
import re
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.core.logging import setup_logger
from app.knowledge.lexical_index import lexical_index
from app.utils.embedding import embeddings


logger = setup_logger("vector_store")


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", value).strip("_-")
    return (cleaned or "default")[:48]


def _get_collection_name(user_id: str, kb_id: str) -> str:
    shard = resolve_vector_shard(user_id, kb_id)
    suffix = "" if settings.vector_shard_count == 1 else f"_s{shard}"
    return f"user_{_safe(user_id)}_kb_{_safe(kb_id)}{suffix}"[:120]


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
        chroma_settings = ChromaSettings(anonymized_telemetry=False)
        urls = [item.strip() for item in settings.vector_shard_urls.split(",") if item.strip()]
        if urls:
            clients = []
            for raw_url in urls:
                parsed = urlparse(raw_url if "://" in raw_url else f"http://{raw_url}")
                if not parsed.hostname or not parsed.port:
                    raise ValueError(f"无效的 VECTOR_SHARD_URLS 地址: {raw_url}")
                clients.append(
                    chromadb.HttpClient(
                        host=parsed.hostname,
                        port=parsed.port,
                        ssl=parsed.scheme == "https",
                        settings=chroma_settings,
                    )
                )
            if settings.vector_shard_count not in {1, len(clients)}:
                raise ValueError("VECTOR_SHARD_COUNT 必须与 VECTOR_SHARD_URLS 数量一致")
            return clients
        if settings.chroma_mode == "http":
            return [chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                settings=chroma_settings,
            )]
        shard_count = max(1, settings.vector_shard_count)
        clients = []
        for shard_id in range(shard_count):
            path = Path(settings.chroma_path)
            if shard_count > 1:
                path = path / f"shard-{shard_id}"
            path.mkdir(parents=True, exist_ok=True)
            clients.append(chromadb.PersistentClient(path=str(path), settings=chroma_settings))
        return clients

    def _client_for(self, user_id: str, kb_id: str) -> Any:
        return self.clients[resolve_vector_shard(user_id, kb_id) % len(self.clients)]

    def heartbeat(self) -> bool:
        for client in self.clients:
            client.heartbeat()
        return True

    def get_or_create_collection(self, user_id: str, kb_id: str) -> Any:
        return self._client_for(user_id, kb_id).get_or_create_collection(
            name=_get_collection_name(user_id, kb_id),
            metadata={
                "user_id": user_id,
                "kb_id": kb_id,
                "vector_shard_id": resolve_vector_shard(user_id, kb_id),
                "vector_shard_count": settings.vector_shard_count,
            },
            embedding_function=embeddings,
        )

    def get_collection(self, user_id: str, kb_id: str) -> Any | None:
        try:
            return self._client_for(user_id, kb_id).get_collection(
                name=_get_collection_name(user_id, kb_id), embedding_function=embeddings
            )
        except Exception:
            return None

    def delete_collection(self, user_id: str, kb_id: str) -> bool:
        name = _get_collection_name(user_id, kb_id)
        try:
            self._client_for(user_id, kb_id).delete_collection(name=name)
            logger.info("知识库向量集合已删除: %s", name)
        except Exception:
            return False
        lexical_index.delete_collection(user_id, kb_id)
        return True

    def delete_document(self, user_id: str, kb_id: str, document_id: str) -> int:
        collection = self.get_collection(user_id, kb_id)
        if collection is None:
            lexical_index.delete_document(user_id, kb_id, document_id)
            return 0
        result = collection.get(where={"document_id": document_id})
        ids = result.get("ids", [])
        if ids:
            collection.delete(ids=ids)
        lexical_index.delete_document(user_id, kb_id, document_id)
        return len(ids)

    def get_document_chunks(
        self, user_id: str, kb_id: str, document_id: str
    ) -> list[dict[str, Any]]:
        collection = self.get_collection(user_id, kb_id)
        if collection is None:
            return []
        result = collection.get(
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
            for collection in client.list_collections()
        ]
        return [
            collection
            for collection in collections
            if (collection.metadata or {}).get("user_id") == user_id
            or collection.name.startswith(f"user_{_safe(user_id)}_kb_")
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
                    "chunk_count": collection.count(),
                    "metadata": metadata,
                }
            )
        return stats

    def get_total_stats(self) -> dict[str, Any]:
        by_shard = []
        collections = []
        for shard_id, client in enumerate(self.clients):
            shard_collections = client.list_collections()
            collections.extend(shard_collections)
            by_shard.append({
                "shard_id": shard_id,
                "collections": len(shard_collections),
                "chunks": sum(collection.count() for collection in shard_collections),
            })
        return {
            "total_collections": len(collections),
            "total_chunks": sum(collection.count() for collection in collections),
            "collection_names": [collection.name for collection in collections],
            "vector_shard_id": settings.vector_shard_id,
            "vector_shard_count": settings.vector_shard_count,
            "active_shard_clients": len(self.clients),
            "shards": by_shard,
        }

    def delete_user_collections(self, user_id: str) -> int:
        deleted = 0
        for client in self.clients:
            for collection in client.list_collections():
                metadata = collection.metadata or {}
                if metadata.get("user_id") == user_id or collection.name.startswith(
                    f"user_{_safe(user_id)}_kb_"
                ):
                    deleted += collection.count()
                    client.delete_collection(collection.name)
        lexical_index.delete_user(user_id)
        return deleted

    def cleanup_orphan_collections(
        self, valid_kb_pairs: set[tuple[str, str]]
    ) -> dict[str, Any]:
        removed: list[str] = []
        kept: list[str] = []
        errors: list[dict[str, str]] = []
        for client in self.clients:
            for collection in client.list_collections():
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
