import asyncio
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import settings
from app.core.logging import setup_logger
from app.knowledge.ingestion import SUPPORTED_EXTENSIONS, ingest_document
from app.knowledge.retriever import retrieve
from app.knowledge.task_tracker import create_task, get_task, update_task
from app.knowledge.vector_store import vector_store
from app.models.knowledge import DocumentIngestRequest, IngestionResult, IngestionTaskResponse, RetrieverResult


router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])
logger = setup_logger("knowledge_api")
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingestion")


def _run_ingestion(
    user_id: str,
    kb_id: str,
    file_path: str,
    task_id: str,
    source_name: str,
    document_id: str | None = None,
    remove_after: bool = True,
) -> None:
    try:
        resolved_document_id = ingest_document(
            user_id, kb_id, file_path, source_name=source_name, document_id=document_id
        )
        collection = vector_store.get_collection(user_id, kb_id)
        chunk_count = 0
        if collection is not None:
            result = collection.get(where={"document_id": resolved_document_id})
            chunk_count = len(result.get("ids", []))
        update_task(
            task_id, "done", chunks=chunk_count, document_id=resolved_document_id
        )
    except Exception as error:
        logger.exception("文档解析失败: %s", error)
        update_task(task_id, "failed", error=str(error))
    finally:
        if remove_after:
            try:
                os.unlink(file_path)
            except OSError:
                pass


@router.post("/upload", response_model=IngestionTaskResponse)
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = "default",
    kb_id: str = "default_kb",
) -> IngestionTaskResponse:
    filename = Path(file.filename or "upload.tmp").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"不支持的文件格式: {extension}")
    content = await file.read(settings.upload_max_mb * 1024 * 1024 + 1)
    if len(content) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.upload_max_mb} MB")
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temporary:
        temporary.write(content)
        temporary_path = temporary.name

    task_id = create_task()
    asyncio.get_running_loop().run_in_executor(
        executor,
        _run_ingestion,
        user_id,
        kb_id,
        temporary_path,
        task_id,
        filename,
    )
    return IngestionTaskResponse(status="processing", task_id=task_id, message="文档正在解析")


@router.post("/ingest", response_model=IngestionTaskResponse)
async def ingest(request: DocumentIngestRequest) -> IngestionTaskResponse:
    path = Path(request.file_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="待解析文件不存在")
    task_id = create_task()
    asyncio.get_running_loop().run_in_executor(
        executor,
        _run_ingestion,
        request.user_id,
        request.kb_id,
        str(path),
        task_id,
        path.name,
        request.document_id,
        False,
    )
    return IngestionTaskResponse(status="processing", task_id=task_id, message="文档正在解析")


@router.post("/internal/ingest", response_model=IngestionResult)
async def ingest_durable(request: DocumentIngestRequest) -> IngestionResult:
    path = Path(request.file_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="待解析文件不存在")
    document_id = await asyncio.get_running_loop().run_in_executor(
        executor,
        ingest_document,
        request.user_id,
        request.kb_id,
        str(path),
        path.name,
        request.document_id,
    )
    collection = vector_store.get_collection(request.user_id, request.kb_id)
    chunks = 0
    if collection is not None:
        chunks = len(collection.get(where={"document_id": document_id}).get("ids", []))
    return IngestionResult(status="done", document_id=document_id, chunks=chunks)


@router.get("/task/{task_id}")
async def task_status(task_id: str) -> dict:
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return task


@router.get("/search", response_model=RetrieverResult)
async def search(query: str, user_id: str, kb_id: str, top_k: int = 5) -> RetrieverResult:
    return RetrieverResult(chunks=retrieve(user_id, kb_id, query, top_k), query=query)


@router.get("/admin/collections")
async def list_collections(user_id: str) -> list[dict]:
    return vector_store.get_collection_stats(user_id)


@router.get("/admin/stats")
async def global_stats() -> dict:
    return vector_store.get_total_stats()


@router.delete("/admin/collections/{kb_id}")
async def delete_collection(kb_id: str, user_id: str) -> dict:
    deleted = vector_store.delete_collection(user_id, kb_id)
    return {"deleted": deleted, "kb_id": kb_id}
