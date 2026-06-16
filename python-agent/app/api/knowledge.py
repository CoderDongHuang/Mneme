import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, UploadFile, File
from app.models.knowledge import DocumentIngestRequest, RetrieverResult
from app.knowledge.ingestion import ingest_document
from app.knowledge.retriever import retrieve
from app.core.logging import setup_logger
import os
import tempfile

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])
logger = setup_logger("knowledge_api")

executor = ThreadPoolExecutor(max_workers=4)

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), user_id: str = "default", kb_id: str = "default_kb"):
    """浏览器文件上传"""
    logger.info(f"收到文件上传: user_id={user_id}, kb_id={kb_id}, filename={file.filename}")

    suffix = os.path.splitext(file.filename)[1] if file.filename else ".tmp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    async def process():
        loop = asyncio.get_event_loop()
        try:
            doc_id = await loop.run_in_executor(
                executor, ingest_document, user_id, kb_id, tmp_path
            )
            logger.info(f"文档解析成功: doc_id={doc_id}")
        except Exception as e:
            logger.error(f"文档解析失败: {e}")
        finally:
            # 确保无论成功还是失败都删除临时文件
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    asyncio.create_task(process())
    return {"status": "parsing", "message": "文档正在解析中"}

@router.post("/ingest")
async def ingest(request: DocumentIngestRequest):
    logger.info(f"收到文档上传请求: user_id={request.user_id}, kb_id={request.kb_id}")

    async def process():
        try:
            doc_id = await asyncio.get_event_loop().run_in_executor(
                executor, ingest_document, request.user_id, request.kb_id, request.file_path
            )
            logger.info(f"文档解析成功: doc_id={doc_id}")
        except Exception as e:
            logger.error(f"文档解析失败: {e}")

    asyncio.create_task(process())
    return {"status": "parsing", "message": "文档正在解析中"}

@router.get("/search", response_model=RetrieverResult)
async def search(query: str, user_id: str, kb_id: str, top_k: int = 5):
    chunks = retrieve(user_id, kb_id, query, top_k)
    return RetrieverResult(chunks=chunks, query=query)


# ── 运维管理接口 ──────────────────────────────────────────

@router.get("/admin/collections")
async def list_collections(user_id: str):
    """列出某用户的所有知识库 collection"""
    from app.knowledge.vector_store import vector_store
    return vector_store.get_collection_stats(user_id)


@router.get("/admin/stats")
async def global_stats():
    """获取全局 Chroma 统计信息"""
    from app.knowledge.vector_store import vector_store
    return vector_store.get_total_stats()


@router.post("/admin/cleanup")
async def cleanup_orphans(valid_kb_pairs: list[tuple[str, str]]):
    """清理孤儿 collection。

    Args:
        valid_kb_pairs: [(user_id, kb_id), ...] 合法的知识库对列表
    """
    from app.knowledge.vector_store import vector_store
    result = vector_store.cleanup_orphan_collections(set(valid_kb_pairs))
    logger.info(f"孤儿 collection 清理完成: 删除 {len(result['removed'])} 个")
    return result
