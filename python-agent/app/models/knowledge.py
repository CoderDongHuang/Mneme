from typing import Any

from pydantic import BaseModel, Field


class DocumentIngestRequest(BaseModel):
    user_id: str
    kb_id: str
    file_path: str
    document_id: str | None = None
    task_id: str | None = Field(default=None, max_length=128)
    source_name: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    content: str
    metadata: dict[str, Any]
    score: float = 0.0
    id: str | None = None
    retrieval_ranks: dict[str, int] = Field(default_factory=dict)
    retrieval_channels: list[str] = Field(default_factory=list)
    distance: float | None = None
    lexical_score: float | None = None
    term_coverage: float | None = None


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
    report: dict[str, Any] = Field(default_factory=dict)
