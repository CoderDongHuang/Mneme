from fastapi import FastAPI
from app.api import chat, knowledge, health

app = FastAPI(title="Mneme Agent", version="0.1.0")

app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(health.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)