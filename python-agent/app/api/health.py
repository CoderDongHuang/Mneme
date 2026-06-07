from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/health")
async def health():
    return {"status": "ok", "services": {"chroma": True, "llm": True}}