import httpx
import os
import logging
import json

logger = logging.getLogger(__name__)

class WorkerClient:
    def __init__(self):
        self.worker_url = os.getenv("WORKER_URL", "http://worker:8000")
        self.timeout = 120.0

    async def call_tool(self, tool: str, arguments: dict) -> dict:
        url = f"{self.worker_url}/api/v1/tool"
        payload = {"tool": tool, "arguments": arguments}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            try:
                return resp.json()
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON response from worker: {resp.text[:200]}")
                return {"status": "error", "error_message": f"Invalid JSON response: {e}"}