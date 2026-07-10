import os
import logging
import httpx

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token or not self.chat_id:
            logger.warning("Telegram notifier not configured: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    async def send_message(self, text: str):
        if not self.token or not self.chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={"chat_id": self.chat_id, "text": text})
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")