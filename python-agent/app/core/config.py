import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # ── LLM ──
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    LLM_FALLBACK_ENABLED = os.getenv("LLM_FALLBACK_ENABLED", "true").lower() == "true"
    LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "qwen-plus")
    LLM_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "3"))

    # ── Chroma ──
    CHROMA_HOST = os.getenv("CHROMA_HOST", "http://localhost:8000")
    CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

    # ── Redis (会话持久化) ──
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB = int(os.getenv("REDIS_DB", "0"))
    SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))

    # ── Memory ──
    WORKING_MEMORY_WINDOW_SIZE = int(os.getenv("WORKING_MEMORY_WINDOW_SIZE", "10"))
    WORKING_MEMORY_MAX_TOKENS = int(os.getenv("WORKING_MEMORY_MAX_TOKENS", "4000"))
    RETRIEVER_TOP_K = int(os.getenv("RETRIEVER_TOP_K", "5"))
    DISTILLATION_IDLE_MINUTES = int(os.getenv("DISTILLATION_IDLE_MINUTES", "15"))

    # ── Other ──
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

settings = Settings()
