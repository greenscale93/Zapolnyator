import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from src.handlers import register_handlers, auto_start_processing

load_dotenv()

logging.basicConfig(level=logging.INFO)

async def main():
    bot = Bot(
        token=os.getenv("TELEGRAM_BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    register_handlers(dp)

    # Запускаем автостарт в фоне
    asyncio.create_task(auto_start_processing(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())