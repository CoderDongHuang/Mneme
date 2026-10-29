import time

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from app.core.user_model import user_model
from app.utils.llm import llm

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.post("/test")
async def test_model():
    config = user_model.get()
    if config is None:
        raise HTTPException(status_code=400, detail="Personal model configuration required")
    start = time.perf_counter()
    try:
        result = await llm.ainvoke([HumanMessage(content="Reply with OK.")], max_tokens=8)
        if not result.content:
            raise ValueError("Empty completion")
    except Exception:
        # Provider exceptions may contain request headers or credentials.
        raise HTTPException(status_code=502, detail="Model test failed; check provider, model and credentials") from None
    return {"status": "ok", "model": config.model, "provider": config.provider,
            "latency_ms": round((time.perf_counter() - start) * 1000)}
