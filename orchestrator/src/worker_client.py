import httpx
import os
from typing import Any, Dict

WORKER_URL = os.getenv("WORKER_URL", "http://worker:8000")

class WorkerClient:
    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{WORKER_URL}/tools/{tool_name}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=params)
            resp.raise_for_status()
            return resp.json()

    async def read_excel_structure(self, file_path: str) -> Dict[str, Any]:
        return await self.call_tool("read_excel_structure", {"file_path": file_path})

    async def apply_sheet_mapping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self.call_tool("apply_sheet_mapping", params)

    async def get_empty_vz_contractors(self, source_path: str) -> list:
        resp = await self.call_tool("read_vz_empty_contractors", {"source_path": source_path})
        if resp.get("status") == "success":
            return resp["result"]["contractors"]
        raise Exception(resp.get("error_message", "Unknown error"))