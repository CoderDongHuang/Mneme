from langchain_community.embeddings import DashScopeEmbeddings
from chromadb import EmbeddingFunction, Documents, Embeddings
from app.core.config import settings

_dashscope_embeddings = DashScopeEmbeddings(
    model="text-embedding-v3",
    dashscope_api_key=settings.DASHSCOPE_API_KEY
)

class DashScopeEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input: Documents) -> Embeddings:
        return _dashscope_embeddings.embed_documents(input)

embeddings = DashScopeEmbeddingFunction()
