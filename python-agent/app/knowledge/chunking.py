from langchain_experimental.text_splitter import SemanticChunker
from app.utils.embedding import embeddings

chunker = SemanticChunker(
    embeddings=embeddings,
    breakpoint_threshold_type="percentile",
    breakpoint_threshold_amount=95
)

def chunk_documents(documents: list) -> list:
    return chunker.split_documents(documents)