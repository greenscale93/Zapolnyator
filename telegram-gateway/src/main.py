import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from src.handlers import register_handlers

from src.api import router as internal_router
app.include_router(internal_router)

load_dotenv()

logging.basicConfig(level=logging.INFO)

async def main():
    bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
    dp = Dispatcher()
    register_handlers(dp)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())