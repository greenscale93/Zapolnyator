import httpx
import os
import logging

logger = logging.getLogger(__name__)

class OrchestratorClient:
    def __init__(self):
        self.base_url = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")

    async def create_task(self, user_id: int, excel_path: str, mxl_path: str, month: str, year: int) -> str:
        url = f"{self.base_url}/api/v1/task"
        payload = {
            "user_id": user_id,
            "files": {
                "excel": excel_path,
                "mxl": mxl_path
            },
            "month": month,
            "year": year
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["task_id"]