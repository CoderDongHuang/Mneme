from typing import Literal

from pydantic import BaseModel, Field

from app.models.chat import Message


class Preference(BaseModel):
    id: str
    content: str
    created_at: str


class WeakPoint(BaseModel):
    id: str
    content: str
    topic: str
    count: int = 1
    created_at: str


class Progress(BaseModel):
    current_chapter: str = ""
    current_section: str = ""
    last_updated: str = ""


class MemoryEntry(BaseModel):
    id: str = ""
    content: str
    category: Literal["preference", "weak_point", "progress"]
    topic: str = ""
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: str = ""
    updated_at: str = ""


class LongTermMemory(BaseModel):
    user_id: str
    preferences: list[Preference] = Field(default_factory=list)
    weak_points: list[WeakPoint] = Field(default_factory=list)
    learning_progress: Progress = Field(default_factory=Progress)
    memory_entries: list[MemoryEntry] = Field(default_factory=list)


class WorkingMemory(BaseModel):
    messages: list[Message] = Field(default_factory=list)
    window_size: int = 10


class ShortTermMemory(BaseModel):
    session_id: str
    full_history: list[Message] = Field(default_factory=list)
    summary: str = ""
    token_count: int = 0


class MemoryReadRequest(BaseModel):
    user_id: str
    memory_types: list[str] = Field(
        default_factory=lambda: ["preference", "weak_point", "progress"]
    )


class MemoryWriteRequest(BaseModel):
    user_id: str
    entry: MemoryEntry


class MemoryReadResponse(BaseModel):
    user_id: str
    preferences: list = Field(default_factory=list)
    weak_points: list = Field(default_factory=list)
    progress: dict | None = None


class MemoryWriteResponse(BaseModel):
    status: str


class SessionInfo(BaseModel):
    id: str
    title: str
    message_count: int
    last_updated: str


class SessionListResponse(BaseModel):
    sessions: list[SessionInfo]
