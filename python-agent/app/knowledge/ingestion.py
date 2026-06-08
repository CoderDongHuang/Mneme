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
    texts = []
    metadatas = []
    for chunk in chunks:
        content = chunk.page_content
        if content and isinstance(content, str) and content.strip():
            texts.append(str(content).strip())
            metadatas.append({"source": os.path.basename(file_path), "page": chunk.metadata.get("page", 0)})

    if not texts:
        raise ValueError("文档解析后没有有效的文本内容")

    logger.info(f"有效文本块数量: {len(texts)}")
    for i, t in enumerate(texts):
        logger.info(f"文本块 {i} 类型: {type(t)}, 长度: {len(t)}, 内容预览: {t[:50]}")
    import uuid
    doc_id = str(uuid.uuid4())[:8]
    ids = [f"{kb_id}_{doc_id}_{i}" for i in range(len(texts))]

    collection.add(documents=texts, metadatas=metadatas, ids=ids)
    logger.info(f"文档解析完成，共 {len(chunks)} 个文档块")
    return f"{kb_id}_doc_{len(chunks)}"