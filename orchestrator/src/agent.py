import logging
import os
import json
import asyncio
import httpx
from src.session_manager import SessionManager
from src.memory import MemoryStore
from src.worker_client import WorkerClient

logger = logging.getLogger(__name__)

class OrchestratorAgent:
    def __init__(self, session_manager: SessionManager, memory_store: MemoryStore, worker_client: WorkerClient):
        self.session_manager = session_manager
        self.memory_store = memory_store
        self.worker_client = worker_client
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.rules = self._load_rules()
        logger.info("OrchestratorAgent initialized")

    def _load_rules(self) -> dict:
        try:
            with open("/app/rules.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Cannot load rules: {e}")
            return {}

    async def _send_telegram_message(self, user_id: int, text: str, file_path: str = None):
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set")
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(url, json=payload)
                if file_path and os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        files = {'document': (os.path.basename(file_path), f, 'text/plain')}
                        await client.post(
                            f"https://api.telegram.org/bot{self.bot_token}/sendDocument",
                            data={'chat_id': user_id},
                            files=files
                        )
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    async def run_agent_cycle(self, task_id: str):
        logger.info(f"Starting agent cycle for task {task_id}")
        state = await self.session_manager.get_session(task_id)
        if not state:
            logger.error(f"Task {task_id} not found")
            return
        
        user_id = state.get("user_id")
        files = state.get("files", {})
        data_file_path = files.get("data")
        excel_path = files.get("excel")
        if not data_file_path or not excel_path:
            await self._set_error(task_id, "Missing file paths")
            await self._send_telegram_message(user_id, "❌ Ошибка: отсутствуют пути к файлам.")
            return

        month = state.get("month", "Май")
        year = state.get("year", 2026)

        if not os.path.exists(data_file_path):
            await self._set_error(task_id, f"Data file not found: {data_file_path}")
            await self._send_telegram_message(user_id, f"❌ Файл с данными не найден: {data_file_path}")
            return

        if not os.path.exists(excel_path):
            await self._set_error(task_id, f"Excel template not found: {excel_path}")
            await self._send_telegram_message(user_id, f"❌ Шаблон не найден: {excel_path}")
            return

        sheets_mapping = self.rules.get("sheets", {})
        if not sheets_mapping:
            await self._set_error(task_id, "No rules found in rules.json")
            await self._send_telegram_message(user_id, "❌ Нет правил для заполнения. Проверьте rules.json.")
            return

        output_path = None  # будет хранить путь к выходному файлу
        first_sheet = True

        for sheet_name, mapping in sheets_mapping.items():
            await self._send_telegram_message(user_id, f"📝 Заполняю лист: {sheet_name}...")
            
            # Для первого листа output_path = None, для остальных — передаём существующий путь
            result = await self.worker_client.call_tool("apply_sheet_mapping", {
                "source_path": data_file_path,
                "template_path": excel_path if output_path is None else output_path,  # если есть output_path, используем его как шаблон
                "sheet_name": sheet_name,
                "mapping": mapping,
                "month": month,
                "year": year,
                "password": "987456",
                "output_path": output_path  # передаём существующий путь, чтобы не создавать новый файл
            })
            if result.get("status") == "error":
                await self._set_error(task_id, result.get("error_message"))
                await self._send_telegram_message(user_id, f"❌ Ошибка при заполнении листа {sheet_name}: {result.get('error_message')}")
                return
            output_path = result["result"]["output_path"]
            rows_added = result["result"].get("rows_added", "неизвестно")
            await self._send_telegram_message(user_id, f"✅ Лист {sheet_name} заполнен (добавлено строк: {rows_added}).")
            first_sheet = False

        if output_path:
            await self._send_telegram_message(user_id,
                "✅ Обработка завершена! Файл будет отправлен."
            )
            await self.session_manager.update_session(task_id, {
                "status": "done",
                "result_file": output_path,
                "metrics": {}
            })
        else:
            await self._set_error(task_id, "No output file generated")

    async def stop_task(self, task_id: str):
        await self.session_manager.update_session(task_id, {
            "status": "cancelled",
            "error": "Остановлено пользователем"
        })
        logger.info(f"Task {task_id} stopped by user")

    async def _set_error(self, task_id: str, error_message: str):
        logger.error(f"Task {task_id} error: {error_message}")
        await self.session_manager.update_session(task_id, {
            "status": "error",
            "error": error_message
        })