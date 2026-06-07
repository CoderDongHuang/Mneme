import chromadb
from chromadb.config import Settings as ChromaSettings
from app.core.config import settings

def _get_collection_name(user_id: str, kb_id: str) -> str:
    return f"user_{user_id}_kb_{kb_id}"

class VectorStore:
    def __init__(self):
        # Docker 环境：通过 HTTP 连接 Chroma 服务
        # 本地开发环境：使用 PersistentClient 直接访问本地路径
        if settings.CHROMA_HOST and settings.CHROMA_HOST != "localhost":
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
            metadata={"user_id": user_id, "kb_id": kb_id}
        )

    def delete_collection(self, user_id: str, kb_id: str):
        collection_name = _get_collection_name(user_id, kb_id)
        try:
            self.client.delete_collection(name=collection_name)
        except Exception:
            pass

vector_store = VectorStore()