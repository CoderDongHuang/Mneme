"""
文档解析与入库

支持的文档格式：PDF、DOCX、Markdown、TXT

PDF 解析策略（按优先级降级）：
1. UnstructuredPDFLoader (mode="elements", strategy="hi_res")
   — 可提取表格、区分标题/正文，适合学习课件
2. PyPDFLoader — 纯文本提取，作为降级方案

每个 chunk 附带 chunk_type 元数据：
- "text" — 普通文本段落
- "table" — 表格内容（UnstructuredPDFLoader 识别）
- "title" — 标题/章节名
"""
import os
import uuid
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredMarkdownLoader
from .chunking import chunk_documents
from .vector_store import vector_store
from app.core.logging import setup_logger

logger = setup_logger("ingestion")


def _get_pdf_loader(file_path: str):
    """获取 PDF 加载器，优先使用 UnstructuredPDFLoader（支持表格），失败降级 PyPDFLoader"""
    try:
        from langchain_community.document_loaders import UnstructuredPDFLoader
        logger.info(f"使用 UnstructuredPDFLoader (hi_res) 解析: {file_path}")
        return UnstructuredPDFLoader(
            file_path,
            mode="elements",       # 按元素类型拆分（表格、标题、正文）
            strategy="hi_res",     # 高精度模式，OCR + 表格识别
        )
    except ImportError:
        logger.warning("UnstructuredPDFLoader 不可用，降级为 PyPDFLoader（纯文本）")
        return PyPDFLoader(file_path)
    except Exception as e:
        logger.warning(f"UnstructuredPDFLoader 初始化失败: {e}，降级为 PyPDFLoader")
        return PyPDFLoader(file_path)


def get_loader(file_path: str):
    """根据文件扩展名获取对应的文档加载器"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return _get_pdf_loader(file_path)
    elif ext in [".docx", ".doc"]:
        return Docx2txtLoader(file_path)
    elif ext in [".md", ".markdown"]:
        return UnstructuredMarkdownLoader(file_path)
    elif ext == ".txt":
        from langchain_community.document_loaders import TextLoader
        return TextLoader(file_path, encoding="utf-8")
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def _infer_chunk_type(chunk) -> str:
    """根据 chunk 元数据推断内容类型"""
    meta = chunk.metadata if hasattr(chunk, "metadata") else {}
    # UnstructuredPDFLoader 会在 metadata 中设置 category
    category = meta.get("category", "")
    if category:
        if category == "Table":
            return "table"
        if category in ("Title", "Header"):
            return "title"
        if category == "ListItem":
            return "text"
    # 启发式判断：包含 | 且有多行结构可能是表格
    content = chunk.page_content if hasattr(chunk, "page_content") else str(chunk)
    if isinstance(content, str) and content.count("|") > 2:
        return "table"
    return "text"


def ingest_document(user_id: str, kb_id: str, file_path: str) -> str:
    """解析文档并入库到向量存储。

    返回文档标识符。
    """
    logger.info(f"开始解析文档: {file_path}")
    loader = get_loader(file_path)
    documents = loader.load()
    logger.info(f"原始文档块数: {len(documents)}")

    # 统计各类型 chunk 数量
    type_counts = {"text": 0, "table": 0, "title": 0}
    for doc in documents:
        chunk_type = _infer_chunk_type(doc)
        type_counts[chunk_type] = type_counts.get(chunk_type, 0) + 1
    logger.info(f"文档元素分布: {type_counts}")

    # 语义分块
    chunks = chunk_documents(documents)

    collection = vector_store.get_or_create_collection(user_id, kb_id)
    texts = []
    metadatas = []

    for chunk in chunks:
        content = chunk.page_content
        if not content or not isinstance(content, str) or not content.strip():
            continue

        chunk_type = _infer_chunk_type(chunk)
        texts.append(content.strip())
        metadatas.append({
            "source": os.path.basename(file_path),
            "page": chunk.metadata.get("page", 0),
            "chunk_type": chunk_type,
        })

    if not texts:
        raise ValueError("文档解析后没有有效的文本内容")

    logger.info(f"有效文本块数量: {len(texts)}")

    doc_id = str(uuid.uuid4())[:8]
    ids = [f"{kb_id}_{doc_id}_{i}" for i in range(len(texts))]

    collection.add(documents=texts, metadatas=metadatas, ids=ids)
    logger.info(
        f"文档入库完成: kb_id={kb_id}, chunks={len(texts)}, "
        f"types={type_counts}"
    )
    return f"{kb_id}_{doc_id}"