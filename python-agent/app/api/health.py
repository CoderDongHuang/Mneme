"""
健康检查端点 — 真实探测下游依赖

- /health      → 存活探针（K8s livenessProbe），1ms 响应
- /health/ready → 就绪探针（K8s readinessProbe），实际检测 Chroma + LLM 可达性
"""
from fastapi import APIRouter
from app.core.logging import setup_logger

logger = setup_logger("health")

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """存活探针：进程是否在运行"""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness():
    """就绪探针：下游依赖是否可达"""
    chroma_ok = False
    llm_ok = False

    # 检测 Chroma
    try:
        from app.memory.memory_store import memory_store
        memory_store.count_user_memories("__health_check__")
        chroma_ok = True
    except Exception as e:
        logger.warning(f"Chroma 就绪检测失败: {e}")

    # 检测 LLM（轻量调用，仅测试连通性）
    try:
        from app.utils.llm import llm
        from langchain_core.messages import HumanMessage
        llm.invoke([HumanMessage(content="ping")], max_tokens=1)
        llm_ok = True
    except Exception as e:
        logger.warning(f"LLM 就绪检测失败: {e}")

    ready = chroma_ok and llm_ok

    return {
        "status": "ready" if ready else "not_ready",
        "chroma": chroma_ok,
        "llm": llm_ok,
    }
