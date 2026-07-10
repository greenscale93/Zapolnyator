import httpx
import os
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)
WORKER_URL = os.getenv("WORKER_URL", "http://worker:8000")

class WorkerClient:
    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{WORKER_URL}/api/v1/tool"
        payload = {"tool": tool_name, "arguments": params}
        logger.info(f"Calling tool {tool_name} at {url}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Tool {tool_name} response: status={data.get('status')}")
            return data

    async def read_excel_structure(self, file_path: str) -> Dict[str, Any]:
        return await self.call_tool("read_excel_structure", {"file_path": file_path})

    async def apply_sheet_mapping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self.call_tool("apply_sheet_mapping", params)

    async def get_empty_vz_contractors(self, source_path: str) -> list:
        resp = await self.call_tool("read_vz_empty_contractors", {"source_path": source_path})
        if resp.get("status") == "success":
            return resp["result"]["contractors"]
        raise Exception(resp.get("error_message", "Unknown error"))

    async def get_template_offices(self, template_path: str) -> list:
        resp = await self.call_tool("read_template_offices", {"template_path": template_path})
        if resp.get("status") == "success":
            return resp["result"]["offices"]
        raise Exception(resp.get("error_message", "Unknown error"))