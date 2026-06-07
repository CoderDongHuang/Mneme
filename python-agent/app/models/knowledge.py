from pydantic import BaseModel
from typing import Dict, Optional

class DocumentIngestRequest(BaseModel):
    user_id: str
    kb_id: str
    file_path: str
    metadata: Optional[Dict] = None

class Chunk(BaseModel):
    content: str
    metadata: Dict
    score: float

class RetrieverResult(BaseModel):
    chunks: list[Chunk]
    query: str