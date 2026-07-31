from typing import Any

from pydantic import BaseModel, Field


class DocumentIngestRequest(BaseModel):
    user_id: str
    kb_id: str
    file_path: str
    document_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    content: str
    metadata: dict[str, Any]
    score: float = 0.0


class RetrieverResult(BaseModel):
    chunks: list[Chunk]
    query: str


class IngestionTaskResponse(BaseModel):
    status: str
    task_id: str
    message: str


class IngestionResult(BaseModel):
    status: str
    document_id: str
    chunks: int
