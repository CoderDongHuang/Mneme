import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    CHROMA_HOST = os.getenv("CHROMA_HOST", "http://localhost:8000")
    CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    WORKING_MEMORY_WINDOW_SIZE = int(os.getenv("WORKING_MEMORY_WINDOW_SIZE", "10"))
    WORKING_MEMORY_MAX_TOKENS = int(os.getenv("WORKING_MEMORY_MAX_TOKENS", "4000"))
    RETRIEVER_TOP_K = int(os.getenv("RETRIEVER_TOP_K", "5"))
    DISTILLATION_IDLE_MINUTES = int(os.getenv("DISTILLATION_IDLE_MINUTES", "15"))

settings = Settings()
