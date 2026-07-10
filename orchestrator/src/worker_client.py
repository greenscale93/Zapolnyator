import httpx
import os
import logging

logger = logging.getLogger(__name__)

class WorkerClient:
    def __init__(self):
        self.worker_url = os.getenv("WORKER_URL", "http://worker:8000")
        self.timeout = 120.0  # увеличенный таймаут

    async def call_tool(self, tool: str, arguments: dict) -> dict:
        url = f"{self.worker_url}/api/v1/tool"
        payload = {"tool": tool, "arguments": arguments}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()