from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.infisical import get_infisical_client
import logging

from app.api.routes import chat, threads, branches, persona, memory, knowledge, notifications

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="RA1 Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/chat")
app.include_router(threads.router, prefix="/api/threads")
app.include_router(branches.router, prefix="/api/branches")
app.include_router(persona.router, prefix="/api/persona")
app.include_router(memory.router, prefix="/api/memory")
app.include_router(knowledge.router, prefix="/api/knowledge")
app.include_router(notifications.router, prefix="/api/notifications")

@app.on_event("startup")
async def startup():
    try:
        get_infisical_client()
        logger.info("Infisical client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Infisical client: {e}")

@app.get("/health")
async def health():
    return {"status": "ok"}


