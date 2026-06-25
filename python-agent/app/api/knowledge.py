import asyncio
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, UploadFile, File
from app.models.knowledge import DocumentIngestRequest, RetrieverResult
from app.knowledge.ingestion import ingest_document
from app.knowledge.retriever import retrieve
from app.knowledge.task_tracker import create_task, update_task, get_task
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])
logger = setup_logger("knowledge_api")

executor = ThreadPoolExecutor(max_workers=4)


def _run_ingestion(user_id: str, kb_id: str, tmp_path: str, task_id: str):
    """在线程池中执行文档解析并更新任务状态"""
    try:
        doc_id = ingest_document(user_id, kb_id, tmp_path)
        logger.info(f"文档解析成功: doc_id={doc_id}")
        update_task(task_id, "done", chunks=1)
    except Exception as e:
        logger.error(f"文档解析失败: {e}")
        update_task(task_id, "failed", error=str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post("/upload", summary="上传文档", description="上传 PDF/DOCX/MD/TXT 文件，异步解析后入库到知识库。返回 task_id 供轮询进度")
async def upload_file(file: UploadFile = File(...), user_id: str = "default", kb_id: str = "default_kb"):
    logger.info(f"收到文件上传: user_id={user_id}, kb_id={kb_id}, filename={file.filename}")

    suffix = os.path.splitext(file.filename)[1] if file.filename else ".tmp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    task_id = create_task()
    asyncio.get_event_loop().run_in_executor(
        executor, _run_ingestion, user_id, kb_id, tmp_path, task_id
    )

    return {"status": "processing", "task_id": task_id, "message": "文档正在解析中"}


@router.post("/ingest")
async def ingest(request: DocumentIngestRequest):
    logger.info(f"收到文档上传请求: user_id={request.user_id}, kb_id={request.kb_id}")

    task_id = create_task()
    asyncio.get_event_loop().run_in_executor(
        executor, _run_ingestion, request.user_id, request.kb_id, request.file_path, task_id
    )

    return {"status": "processing", "task_id": task_id, "message": "文档正在解析中"}


@router.get("/task/{task_id}")
async def task_status(task_id: str):
    """查询文档解析任务进度"""
    task = get_task(task_id)
    if task is None:
        return {"status": "not_found", "message": "任务不存在或已过期"}
    return task


@router.get("/search", response_model=RetrieverResult, summary="知识检索", description="在指定知识库中语义检索相关内容，返回 top_k 条匹配片段")
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
    """清理孤儿 collection"""
    from app.knowledge.vector_store import vector_store
    result = vector_store.cleanup_orphan_collections(set(valid_kb_pairs))
    logger.info(f"孤儿 collection 清理完成: 删除 {len(result['removed'])} 个")
    return result
