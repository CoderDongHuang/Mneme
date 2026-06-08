from langchain_experimental.text_splitter import SemanticChunker
from langchain_community.embeddings import DashScopeEmbeddings
from app.core.config import settings

_langchain_embeddings = DashScopeEmbeddings(
    model="text-embedding-v3",
    dashscope_api_key=settings.DASHSCOPE_API_KEY
)

chunker = SemanticChunker(
    embeddings=_langchain_embeddings,
    breakpoint_threshold_type="percentile",
    breakpoint_threshold_amount=95
)

def chunk_documents(documents: list) -> list:
    return chunker.split_documents(documents)