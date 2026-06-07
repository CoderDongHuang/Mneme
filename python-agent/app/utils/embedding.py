from langchain_community.embeddings import DashScopeEmbeddings
from app.core.config import settings

embeddings = DashScopeEmbeddings(
    model="text-embedding-v3",
    dashscope_api_key=settings.DASHSCOPE_API_KEY
)
