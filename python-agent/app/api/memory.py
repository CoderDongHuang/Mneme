from fastapi import APIRouter
from app.models.memory import (
    MemoryReadRequest, MemoryWriteRequest,
    MemoryReadResponse, MemoryWriteResponse,
)
from app.models.chat import MemoryConfirmRequest
from app.memory.long_term_memory import long_term_memory
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])
logger = setup_logger("memory_api")

@router.post("/read", summary="读取用户记忆", description="读取指定用户的偏好、薄弱点和学习进度",
            response_model=MemoryReadResponse)
async def read_memory(request: MemoryReadRequest):
    result = {"user_id": request.user_id}
    if "preference" in request.memory_types:
        result["preferences"] = long_term_memory.get_preferences(request.user_id)
    if "weak_point" in request.memory_types:
        result["weak_points"] = long_term_memory.get_weak_points(request.user_id)
    if "progress" in request.memory_types:
        result["progress"] = long_term_memory.get_progress(request.user_id)
    return result

@router.post("/write", summary="写入记忆", description="手动写入一条长期记忆（偏好/薄弱点/进度）",
            response_model=MemoryWriteResponse)
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


@router.post("/confirm", summary="确认/拒绝记忆", description="用户对蒸馏产出的中等置信度记忆进行确认或拒绝")
async def confirm_memory(request: MemoryConfirmRequest):
    """用户确认或拒绝待确认的记忆条目。

    - confirm: 写入长期记忆
    - dismiss: 丢弃该记忆
    """
    logger.info(
        f"记忆确认: user={request.user_id}, "
        f"action={request.action}, temp_id={request.temp_id[:20]}"
    )

    if request.action == "confirm":
        # 写入长期记忆
        if request.category == "preference":
            long_term_memory.add_preference(request.user_id, request.content)
        elif request.category == "weak_point":
            long_term_memory.add_weak_point(
                request.user_id, request.content, request.topic or request.content
            )
        elif request.category == "progress":
            parts = request.content.split("/")
            chapter = parts[0] if parts else ""
            section = parts[1] if len(parts) > 1 else ""
            long_term_memory.update_progress(request.user_id, chapter, section)
        return {"status": "confirmed", "action": "written"}

    elif request.action == "dismiss":
        logger.info(f"用户丢弃记忆: {request.content[:50]}")
        return {"status": "dismissed", "action": "discarded"}

    else:
        return {"status": "error", "message": f"未知操作: {request.action}"}
