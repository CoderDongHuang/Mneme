from fastapi import APIRouter
from app.models.knowledge import DocumentIngestRequest, RetrieverResult
from app.knowledge.ingestion import ingest_document
from app.knowledge.retriever import retrieve
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])
logger = setup_logger("knowledge_api")

@router.post("/ingest")
async def ingest(request: DocumentIngestRequest):
    logger.info(f"收到文档上传请求: user_id={request.user_id}, kb_id={request.kb_id}")
    doc_id = ingest_document(request.user_id, request.kb_id, request.file_path)
    return {"status": "success", "document_id": doc_id}

@router.get("/search", response_model=RetrieverResult)
async def search(query: str, user_id: str, kb_id: str, top_k: int = 5):
    chunks = retrieve(user_id, kb_id, query, top_k)
    return RetrieverResult(chunks=chunks, query=query)