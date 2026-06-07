from langchain_deepseek import ChatDeepSeek
from app.core.config import settings

llm = ChatDeepSeek(
    model="deepseek-chat",
    api_key=settings.DEEPSEEK_API_KEY,
    temperature=0.7
)