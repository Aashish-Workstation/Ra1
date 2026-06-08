from fastapi import FastAPI
from app.infisical import get_infisical_client
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="RA1 Backend", version="0.1.0")

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


