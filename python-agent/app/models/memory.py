from pydantic import BaseModel
from typing import List, Optional, Dict
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
    id: str
    content: str
    category: str  # preference / weak_point / progress
    topic: str = ""
    importance_score: float = 0.5
    created_at: str
    updated_at: str

class LongTermMemory(BaseModel):
    user_id: str
    preferences: List[Preference] = []
    weak_points: List[WeakPoint] = []
    learning_progress: Progress = Progress()
    memory_entries: List[MemoryEntry] = []

class WorkingMemory(BaseModel):
    messages: List[Message] = []
    window_size: int = 10

class ShortTermMemory(BaseModel):
    session_id: str
    full_history: List[Message] = []
    summary: str = ""
    token_count: int = 0

class MemoryReadRequest(BaseModel):
    user_id: str
    memory_types: List[str] = ["preference", "weak_point", "progress"]

class MemoryWriteRequest(BaseModel):
    user_id: str
    entry: MemoryEntry
