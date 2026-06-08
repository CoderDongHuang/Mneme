import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"  # 禁用 Chroma 遥测，避免 capture() 参数错误

import chromadb
from chromadb.config import Settings as ChromaSettings
from app.core.config import settings
from app.utils.embedding import embeddings

def _get_collection_name(user_id: str, kb_id: str) -> str:
    return f"user_{user_id}_kb_{kb_id}"

class VectorStore:
    def __init__(self):
        # Docker 环境：通过 HTTP 连接 Chroma 服务
        # 本地开发环境：使用 PersistentClient 直接访问本地路径
        chroma_host = settings.CHROMA_HOST or ""
        is_remote = chroma_host and "localhost" not in chroma_host and "127.0.0.1" not in chroma_host
        if is_remote:
            self.client = chromadb.HttpClient(
                host=settings.CHROMA_HOST,
                port=settings.CHROMA_PORT,
                settings=ChromaSettings(anonymized_telemetry=False)
            )
        else:
            self.client = chromadb.PersistentClient(
                path="./data/chroma",
                settings=ChromaSettings(anonymized_telemetry=False)
            )

    def get_or_create_collection(self, user_id: str, kb_id: str):
        collection_name = _get_collection_name(user_id, kb_id)
        return self.client.get_or_create_collection(
            name=collection_name,
            metadata={"user_id": user_id, "kb_id": kb_id},
            embedding_function=embeddings
        )

    def delete_collection(self, user_id: str, kb_id: str):
        collection_name = _get_collection_name(user_id, kb_id)
        try:
            self.client.delete_collection(name=collection_name)
        except Exception:
            pass

vector_store = VectorStore()