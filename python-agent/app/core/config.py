import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PYTHON_AGENT_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = PYTHON_AGENT_DIR.parent
load_dotenv(PROJECT_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "").strip()
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    fallback_model: str = os.getenv("LLM_FALLBACK_MODEL", "qwen-plus")
    fallback_enabled: bool = _bool("LLM_FALLBACK_ENABLED", True)
    circuit_breaker_threshold: int = int(
        os.getenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "3")
    )
    circuit_recovery_seconds: int = int(os.getenv("LLM_CIRCUIT_RECOVERY_SECONDS", "60"))
    stream_timeout_seconds: int = int(os.getenv("LLM_STREAM_TIMEOUT_SECONDS", "20"))
    llm_hourly_limit: int = int(os.getenv("LLM_HOURLY_LIMIT", "0"))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")

    chroma_mode: str = os.getenv("CHROMA_MODE", "local").lower()
    chroma_host: str = os.getenv("CHROMA_HOST", "localhost")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8000"))
    chroma_path: str = os.getenv(
        "CHROMA_PATH", str(PYTHON_AGENT_DIR / "data" / "chroma")
    )

    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_password: str = os.getenv("REDIS_PASSWORD", "")
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "24"))

    working_memory_window_size: int = int(os.getenv("WORKING_MEMORY_WINDOW_SIZE", "12"))
    working_memory_max_tokens: int = int(os.getenv("WORKING_MEMORY_MAX_TOKENS", "5000"))
    retriever_top_k: int = int(os.getenv("RETRIEVER_TOP_K", "6"))
    distillation_idle_minutes: int = int(os.getenv("DISTILLATION_IDLE_MINUTES", "15"))
    memory_reflection_every_sessions: int = int(
        os.getenv("MEMORY_REFLECTION_EVERY_SESSIONS", "5")
    )

    upload_max_mb: int = int(os.getenv("UPLOAD_MAX_MB", "30"))
    upload_dir: str = os.getenv(
        "UPLOAD_DIR", str(PYTHON_AGENT_DIR / "data" / "uploads")
    )
    ocr_enabled: bool = _bool("OCR_ENABLED", True)
    ocr_languages: str = os.getenv("OCR_LANGUAGES", "chi_sim+eng")
    pdf_min_text_chars: int = int(os.getenv("PDF_MIN_TEXT_CHARS", "80"))
    multimodal_enabled: bool = _bool("MULTIMODAL_ENABLED", False)
    multimodal_model: str = os.getenv("MULTIMODAL_MODEL", "qwen-vl-plus")
    multimodal_max_images: int = int(os.getenv("MULTIMODAL_MAX_IMAGES", "8"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    cors_origins: str = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    )
    internal_service_token: str = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
    skip_internal_auth: bool = _bool("SKIP_INTERNAL_AUTH", False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    # Compatibility aliases retained for the existing memory modules.
    DEEPSEEK_API_KEY = property(lambda self: self.deepseek_api_key)
    DASHSCOPE_API_KEY = property(lambda self: self.dashscope_api_key)
    DEEPSEEK_MODEL = property(lambda self: self.deepseek_model)
    LLM_FALLBACK_MODEL = property(lambda self: self.fallback_model)
    LLM_FALLBACK_ENABLED = property(lambda self: self.fallback_enabled)
    LLM_CIRCUIT_BREAKER_THRESHOLD = property(
        lambda self: self.circuit_breaker_threshold
    )
    CHROMA_HOST = property(lambda self: self.chroma_host)
    CHROMA_PORT = property(lambda self: self.chroma_port)
    REDIS_HOST = property(lambda self: self.redis_host)
    REDIS_PORT = property(lambda self: self.redis_port)
    REDIS_DB = property(lambda self: self.redis_db)
    REDIS_PASSWORD = property(lambda self: self.redis_password)
    SESSION_TTL_HOURS = property(lambda self: self.session_ttl_hours)
    WORKING_MEMORY_WINDOW_SIZE = property(lambda self: self.working_memory_window_size)
    WORKING_MEMORY_MAX_TOKENS = property(lambda self: self.working_memory_max_tokens)
    RETRIEVER_TOP_K = property(lambda self: self.retriever_top_k)
    DISTILLATION_IDLE_MINUTES = property(lambda self: self.distillation_idle_minutes)
    LOG_LEVEL = property(lambda self: self.log_level)


settings = Settings()
