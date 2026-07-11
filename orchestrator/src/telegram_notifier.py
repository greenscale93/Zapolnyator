import os
import json
import logging
import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Отправка сообщений и документов в Telegram.

    Поддерживает как отправку конкретному пользователю (user_id),
    так и отправку в глобальный чат (TELEGRAM_CHAT_ID).
    """

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.default_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token:
            logger.warning(
                "Telegram notifier not configured: missing TELEGRAM_BOT_TOKEN"
            )

    async def send_message(
        self,
        text: str,
        user_id: int = None,
        reply_markup: dict = None
    ):
        """Отправляет текстовое сообщение."""
        if not self.token:
            return
        chat_id = user_id if user_id else self.default_chat_id
        if not chat_id:
            logger.warning("No chat_id or user_id specified for Telegram message")
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    async def send_document(
        self,
        file_path: str,
        caption: str = None,
        user_id: int = None
    ):
        """Отправляет файл как документ."""
        if not self.token or not os.path.exists(file_path):
            return
        chat_id = user_id if user_id else self.default_chat_id
        if not chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendDocument"
            with open(file_path, 'rb') as f:
                files = {'document': (os.path.basename(file_path), f, 'text/plain')}
                data = {'chat_id': chat_id}
                if caption:
                    data['caption'] = caption
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(url, data=data, files=files)
                    resp.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send Telegram document: {e}")