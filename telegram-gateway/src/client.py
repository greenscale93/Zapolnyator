import httpx
import os
import logging
import asyncio

logger = logging.getLogger(__name__)

class OrchestratorClient:
    def __init__(self):
        self.base_url = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")
        self.max_retries = 5
        self.retry_delay = 2  # секунды

    async def _request_with_retry(self, method: str, url: str, **kwargs):
        """Выполняет HTTP-запрос с повторными попытками при ошибках соединения."""
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.request(method, url, **kwargs)
                    response.raise_for_status()
                    return response.json()
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Connection error (attempt {attempt+1}/{self.max_retries}): {e}")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error(f"Failed to connect after {self.max_retries} attempts")
                    raise
            except Exception as e:
                logger.error(f"Request error: {e}")
                raise

    async def create_task(self, user_id: int, excel_path: str, data_path: str, month: str, year: int) -> str:
        url = f"{self.base_url}/api/v1/task"
        payload = {
            "user_id": user_id,
            "files": {
                "excel": excel_path,
                "data": data_path
            },
            "month": month,
            "year": year
        }
        data = await self._request_with_retry("POST", url, json=payload)
        return data["task_id"]

    async def get_task_status(self, task_id: str) -> dict:
        url = f"{self.base_url}/api/v1/task/{task_id}"
        return await self._request_with_retry("GET", url)

    async def answer_question(self, task_id: str, answer: str) -> dict:
        url = f"{self.base_url}/api/v1/task/{task_id}/answer"
        payload = {"answer": answer}
        return await self._request_with_retry("POST", url, json=payload)
    
    async def approve_llm(self, task_id: str):
        url = f"{self.base_url}/api/v1/task/{task_id}/approve"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url)
            resp.raise_for_status()
            return resp.json()

    async def cancel_llm(self, task_id: str):
        url = f"{self.base_url}/api/v1/task/{task_id}/cancel"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url)
            resp.raise_for_status()
            return resp.json()

    async def stop_task(self, task_id: str):
        url = f"{self.base_url}/api/v1/task/{task_id}/stop"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url)
            resp.raise_for_status()
            return resp.json()