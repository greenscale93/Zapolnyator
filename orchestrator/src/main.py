import logging
from fastapi import FastAPI
from src.api import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Orchestrator")
app.include_router(router)

@app.get("/health")
async def health():
    return {"status": "ok"}