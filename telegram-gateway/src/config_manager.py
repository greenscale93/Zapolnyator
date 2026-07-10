import os
import json
import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
_redis_client = None

async def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client

async def get_autotest_status() -> bool:
    """Возвращает текущий статус автотеста из Redis"""
    try:
        r = await get_redis()
        value = await r.get("autotest:enabled")
        if value is None:
            # Если ключа нет, берём из переменной окружения
            return os.getenv("AUTO_TEST", "false").lower() == "true"
        return value.lower() == "true"
    except Exception as e:
        print(f"Error reading autotest status: {e}")
        return os.getenv("AUTO_TEST", "false").lower() == "true"

async def set_autotest_status(enabled: bool):
    """Устанавливает статус автотеста в Redis"""
    try:
        r = await get_redis()
        await r.set("autotest:enabled", "true" if enabled else "false")
    except Exception as e:
        print(f"Error setting autotest status: {e}")