from fastapi import APIRouter
from app.models.memory import MemoryReadRequest, MemoryWriteRequest, LongTermMemory
from app.memory.long_term_memory import long_term_memory
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])
logger = setup_logger("memory_api")

@router.post("/read")
async def read_memory(request: MemoryReadRequest):
    result = {"user_id": request.user_id}
    if "preference" in request.memory_types:
        result["preferences"] = long_term_memory.get_preferences(request.user_id)
    if "weak_point" in request.memory_types:
        result["weak_points"] = long_term_memory.get_weak_points(request.user_id)
    if "progress" in request.memory_types:
        result["progress"] = long_term_memory.get_progress(request.user_id)
    return result

@router.post("/write")
async def write_memory(request: MemoryWriteRequest):
    entry = request.entry
    if entry.category == "preference":
        long_term_memory.add_preference(request.user_id, entry.content)
    elif entry.category == "weak_point":
        long_term_memory.add_weak_point(request.user_id, entry.content, entry.topic or entry.content)
    elif entry.category == "progress":
        # 简单解析 chapter/section
        parts = entry.content.split("/")
        chapter = parts[0] if len(parts) > 0 else ""
        section = parts[1] if len(parts) > 1 else ""
        long_term_memory.update_progress(request.user_id, chapter, section)
    return {"status": "success"}
