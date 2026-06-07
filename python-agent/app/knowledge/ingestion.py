import os
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredMarkdownLoader
from .chunking import chunk_documents
from .vector_store import vector_store
from app.core.logging import setup_logger

logger = setup_logger("ingestion")

def get_loader(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return PyPDFLoader(file_path)
    elif ext in [".docx", ".doc"]:
        return Docx2txtLoader(file_path)
    elif ext in [".md", ".markdown"]:
        return UnstructuredMarkdownLoader(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")

def ingest_document(user_id: str, kb_id: str, file_path: str) -> str:
    logger.info(f"开始解析文档: {file_path}")
    loader = get_loader(file_path)
    documents = loader.load()
    chunks = chunk_documents(documents)

    collection = vector_store.get_or_create_collection(user_id, kb_id)
    texts = [chunk.page_content for chunk in chunks]
    metadatas = [{"source": os.path.basename(file_path), "page": chunk.metadata.get("page", 0)} for chunk in chunks]
    import uuid
    doc_id = str(uuid.uuid4())[:8]
    ids = [f"{kb_id}_{doc_id}_{i}" for i in range(len(texts))]

    collection.add(documents=texts, metadatas=metadatas, ids=ids)
    logger.info(f"文档解析完成，共 {len(chunks)} 个文档块")
    return f"{kb_id}_doc_{len(chunks)}"