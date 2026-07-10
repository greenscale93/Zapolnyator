import redis.asyncio as redis
import json
import os
import logging

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
        self.client = redis.from_url(self.redis_url, decode_responses=True)

    async def init_session(self, task_id: str, user_id: int, files: dict, month: str, year: int):
        data = {
            "user_id": user_id,
            "files": files,
            "month": month,
            "year": year,
            "status": "processing",
            "history": []  # для диалога с DeepSeek
        }
        await self.client.setex(f"session:{task_id}", 3600, json.dumps(data))

    async def get_session(self, task_id: str):
        raw = await self.client.get(f"session:{task_id}")
        if raw:
            return json.loads(raw)
        return None

    async def update_session(self, task_id: str, updates: dict):
        current = await self.get_session(task_id)
        if current:
            current.update(updates)
            await self.client.setex(f"session:{task_id}", 3600, json.dumps(current))

    async def delete_session(self, task_id: str):
        await self.client.delete(f"session:{task_id}")