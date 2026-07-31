from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str
    token_count: int = 0


class ChatRequest(BaseModel):
    request_id: str = Field(default="", max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)
    knowledge_base_ids: list[str] = Field(default_factory=list)

    @field_validator("user_id", "session_id", "message")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class Source(BaseModel):
    document_name: str
    chunk_content: str
    page: int | None = None
    score: float = 0.0
    chunk_type: str = "text"


class PendingMemory(BaseModel):
    temp_id: str
    category: Literal["preference", "weak_point", "progress"]
    content: str
    topic: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryConfirmRequest(BaseModel):
    user_id: str
    temp_id: str
    action: Literal["confirm", "dismiss"]
    category: str = ""
    content: str = ""
    topic: str = ""


class ChatResponse(BaseModel):
    answer: str
    intent: str = "qa"
    sources: list[Source] = Field(default_factory=list)
    session_summary: str | None = None
    memory_insights: list[str] = Field(default_factory=list)
    pending_memories: list[PendingMemory] = Field(default_factory=list)
