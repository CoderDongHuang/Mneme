from pydantic import BaseModel, field_validator
from typing import List, Optional

MAX_MESSAGE_LENGTH = 4000

class Message(BaseModel):
    role: str
    content: str
    timestamp: str
    token_count: int

class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str
    knowledge_base_ids: List[str] = []

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息不能为空")
        if len(v) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"消息长度不能超过 {MAX_MESSAGE_LENGTH} 字符")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_id 不能为空")
        return v.strip()

class Source(BaseModel):
    document_name: str
    chunk_content: str
    page: Optional[int]
    score: float

class PendingMemory(BaseModel):
    """待用户确认的记忆条目"""
    temp_id: str          # 临时 ID，用于确认/拒绝
    category: str         # preference / weak_point / progress
    content: str
    topic: str = ""       # 薄弱点主题
    confidence: float     # LLM 给出的置信度 (0.6-0.8)

class MemoryConfirmRequest(BaseModel):
    """记忆确认请求"""
    user_id: str
    temp_id: str          # 临时 ID
    action: str           # "confirm" | "dismiss"
    category: str = ""    # 记忆类别（confirm 时需要）
    content: str = ""     # 记忆内容（confirm 时需要）
    topic: str = ""       # 薄弱点主题

class ChatResponse(BaseModel):
    answer: str
    sources: List[Source]
    session_summary: Optional[str] = None
    memory_insights: List[str] = []
    pending_memories: List[PendingMemory] = []  # 待用户确认的记忆