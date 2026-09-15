import asyncio
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.logging import setup_logger
from app.knowledge.ingestion import SUPPORTED_EXTENSIONS, ingest_document
from app.knowledge.retriever import retrieve
from app.knowledge.task_tracker import create_task, get_task, update_task
from app.knowledge.vector_store import vector_store
from app.utils.llm import llm
from app.models.knowledge import (
    DocumentIngestRequest,
    IngestionResult,
    IngestionTaskResponse,
    RetrieverResult,
)


router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])
logger = setup_logger("knowledge_api")
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingestion")


class QuizGenerationRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    chunks: list[dict] = Field(min_length=1, max_length=8)


class GeneratedQuestion(BaseModel):
    id: int
    type: str
    prompt: str = Field(min_length=4, max_length=500)
    options: list[str] = Field(default_factory=list, max_length=6)
    answer: str
    key_points: list[str] = Field(min_length=1, max_length=5)
    evidence: str = Field(min_length=1, max_length=1000)
    source: dict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in {"choice", "short"}:
            raise ValueError("type must be choice or short")
        return value

    @field_validator("options")
    @classmethod
    def valid_options(cls, value: list[str], info) -> list[str]:
        if info.data.get("type") == "choice" and len(value) < 2:
            raise ValueError("choice question requires at least two options")
        return value


def _quiz_json(content: str) -> list[dict]:
    match = re.search(r"\[.*\]", content, flags=re.DOTALL)
    if not match:
        raise ValueError("模型未返回 JSON 数组")
    raw = json.loads(match.group(0))
    return [GeneratedQuestion.model_validate(item).model_dump() for item in raw]


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
        raise HTTPException(
            status_code=413, detail=f"文件不能超过 {settings.upload_max_mb} MB"
        )
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
    return IngestionTaskResponse(
        status="processing", task_id=task_id, message="文档正在解析"
    )


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
    return IngestionTaskResponse(
        status="processing", task_id=task_id, message="文档正在解析"
    )


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
async def search(
    query: str, user_id: str, kb_id: str, top_k: int = 5
) -> RetrieverResult:
    return RetrieverResult(chunks=retrieve(user_id, kb_id, query, top_k), query=query)


@router.post("/quiz/generate")
async def generate_quiz(request: QuizGenerationRequest) -> dict:
    evidence = "\n\n".join(
        f"片段 {index + 1}：{chunk.get('content', '')[:1600]}\n来源：{json.dumps(chunk.get('metadata', {}), ensure_ascii=False)}"
        for index, chunk in enumerate(request.chunks)
    )
    prompt = f"""你是学习测验设计器。只能依据证据，为主题“{request.topic}”生成 3 道题。
前两题为 choice，最后一题为 short。干扰项必须合理但不能被证据支持。
每题必须包含 id、type、prompt、options、answer、key_points、evidence、source。
choice 的 answer 是正确选项下标字符串；short 的 key_points 是评分要点。
evidence 必须是证据原文，source 必须复制对应来源对象。只输出 JSON 数组。

证据：
{evidence}"""
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        questions = _quiz_json(str(response.content))
        if not 1 <= len(questions) <= 5:
            raise ValueError("题目数量不合法")
        return {"questions": questions}
    except Exception as error:
        logger.warning("LLM 结构化出题失败: %s", error)
        raise HTTPException(status_code=503, detail="模型暂时无法生成有效测验") from error


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


@router.delete("/admin/documents/{document_id}")
async def delete_document(document_id: str, user_id: str, kb_id: str) -> dict:
    deleted = vector_store.delete_document(user_id, kb_id, document_id)
    return {"deleted_chunks": deleted, "document_id": document_id}


@router.delete("/admin/user/{user_id}")
async def delete_user_collections(user_id: str) -> dict:
    deleted = 0
    for collection in vector_store.list_user_collections(user_id):
        deleted += collection.count()
        vector_store.client.delete_collection(collection.name)
    from app.knowledge.lexical_index import lexical_index

    lexical_index.delete_user(user_id)
    return {"status": "deleted", "user_id": user_id, "chunks": deleted}
