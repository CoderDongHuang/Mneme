from pydantic import BaseModel
from typing import List, Optional, Dict

class Message(BaseModel):
    role: str
    content: str
    timestamp: str
    token_count: int

class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str
    knowledge_base_ids: List[str] = []  # 空列表 = 纯对话模式

class Source(BaseModel):
    document_name: str
    chunk_content: str
    page: Optional[int]
    score: float

class ChatResponse(BaseModel):
    answer: str
    sources: List[Source]
    session_summary: Optional[str] = None
    memory_insights: List[str] = []