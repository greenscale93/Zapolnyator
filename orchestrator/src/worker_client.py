import httpx
import logging
import os

logger = logging.getLogger(__name__)

class WorkerClient:
    def __init__(self):
        self.worker_url = os.getenv("WORKER_URL", "http://worker:8000")

    async def call_tool(self, tool: str, arguments: dict) -> dict:
        # Пока заглушка – возвращаем фиктивные данные
        logger.info(f"Вызов инструмента {tool} с аргументами {arguments}")
        # Здесь будет реальный POST запрос к Worker
        return {"status": "success", "result": {"mock": True}}