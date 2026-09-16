import os
import re
import hashlib
from pathlib import Path
from typing import Any

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
        self.client = self._build_client()

    def _build_client(self) -> Any:
        chroma_settings = ChromaSettings(anonymized_telemetry=False)
        if settings.chroma_mode == "http":
            return chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                settings=chroma_settings,
            )
        Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(
            path=settings.chroma_path, settings=chroma_settings
        )

    def heartbeat(self) -> bool:
        self.client.heartbeat()
        return True

    def get_or_create_collection(self, user_id: str, kb_id: str) -> Any:
        return self.client.get_or_create_collection(
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
            return self.client.get_collection(
                name=_get_collection_name(user_id, kb_id), embedding_function=embeddings
            )
        except Exception:
            return None

    def delete_collection(self, user_id: str, kb_id: str) -> bool:
        name = _get_collection_name(user_id, kb_id)
        try:
            self.client.delete_collection(name=name)
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

    def list_user_collections(self, user_id: str) -> list[Any]:
        collections = self.client.list_collections()
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
        collections = self.client.list_collections()
        return {
            "total_collections": len(collections),
            "total_chunks": sum(collection.count() for collection in collections),
            "collection_names": [collection.name for collection in collections],
            "vector_shard_id": settings.vector_shard_id,
            "vector_shard_count": settings.vector_shard_count,
        }

    def cleanup_orphan_collections(
        self, valid_kb_pairs: set[tuple[str, str]]
    ) -> dict[str, Any]:
        removed: list[str] = []
        kept: list[str] = []
        errors: list[dict[str, str]] = []
        for collection in self.client.list_collections():
            metadata = collection.metadata or {}
            user_id = str(metadata.get("user_id", ""))
            kb_id = str(metadata.get("kb_id", ""))
            if not user_id or not kb_id:
                continue
            if (user_id, kb_id) in valid_kb_pairs:
                kept.append(collection.name)
                continue
            try:
                self.client.delete_collection(collection.name)
                removed.append(collection.name)
            except Exception as error:
                errors.append({"name": collection.name, "error": str(error)})
        return {"removed": removed, "kept": kept, "errors": errors}


vector_store = VectorStore()
