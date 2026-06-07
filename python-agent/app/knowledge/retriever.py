from .vector_store import vector_store
from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("retriever")

def retrieve(user_id: str, kb_id: str, query: str, top_k: int = None) -> list:
    top_k = top_k or settings.RETRIEVER_TOP_K
    collection = vector_store.get_or_create_collection(user_id, kb_id)
    results = collection.query(query_texts=[query], n_results=top_k)

    chunks = []
    for i in range(len(results["ids"][0])):
        chunks.append({
            "content": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "score": results["distances"][0][i] if "distances" in results else 0.0
        })
    return chunks