import logging
import os
import json
from openai import AsyncOpenAI
from src.session_manager import SessionManager
from src.memory import MemoryStore
from src.worker_client import WorkerClient

logger = logging.getLogger(__name__)

class OrchestratorAgent:
    def __init__(self, session_manager: SessionManager, memory_store: MemoryStore, worker_client: WorkerClient):
        self.session_manager = session_manager
        self.memory_store = memory_store
        self.worker_client = worker_client
        self.client = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/v1"
        )

    async def run_agent_cycle(self, task_id: str):
        state = await self.session_manager.get_session(task_id)
        if not state:
            return
        
        # Загружаем правила из памяти
        rules = await self.memory_store.load_all_rules()
        user_mapping = state.get("user_mapping")  # может быть сохранён после ответа
        
        files = state.get("files", {})
        month = state.get("month", "Май")
        year = state.get("year", 2026)
        
        # 1. Вызов parse_mxl
        parse_result = await self.worker_client.call_tool("parse_mxl", {"file_path": files.get("mxl")})
        if parse_result["status"] == "error":
            await self._set_error(task_id, parse_result.get("error_message"))
            return
        mxl_data = parse_result["result"]["data"]
        
        # 2. Вызов process_data с возможным user_mapping
        process_args = {
            "mxl_data": mxl_data,
            "month": month,
            "year": year,
            "rules": rules
        }
        if user_mapping:
            process_args["user_mapping"] = user_mapping
        
        process_result = await self.worker_client.call_tool("process_data", process_args)
        if process_result["status"] == "error":
            await self._set_error(task_id, process_result.get("error_message"))
            return
        elif process_result["status"] == "needs_clarification":
            # Сохраняем вопрос и ожидаем ответ
            clarification = process_result["clarification"]
            await self.session_manager.update_session(task_id, {
                "status": "waiting_question",
                "question": {"text": clarification["question"], "context": clarification["context"]},
                "pending_tool": "process_data",
                "pending_args": process_args  # сохраняем аргументы для повторного вызова
            })
            return
        
        # Если всё успешно – продолжаем
        processed_data = process_result["result"]
        
        # 3. Вызов update_excel
        excel_result = await self.worker_client.call_tool("update_excel", {
            "template_path": files.get("excel"),
            "data": processed_data,
            "month": month,
            "year": year,
            "password": os.getenv("DEFAULT_PASSWORD", "987456")
        })
        if excel_result["status"] == "error":
            await self._set_error(task_id, excel_result.get("error_message"))
            return
        output_path = excel_result["result"]["output_path"]
        
        # 4. Вызов calculate_metrics
        metrics_result = await self.worker_client.call_tool("calculate_metrics", {
            "output_path": output_path,
            "month": month,
            "year": year,
            "payroll_data": processed_data.get("payroll_rows")
        })
        if metrics_result["status"] == "error":
            await self._set_error(task_id, metrics_result.get("error_message"))
            return
        metrics = metrics_result["result"]
        
        # 5. Завершение
        await self.session_manager.update_session(task_id, {
            "status": "done",
            "result_file": output_path,
            "metrics": metrics
        })

    async def process_answer(self, task_id: str, answer: str):
        state = await self.session_manager.get_session(task_id)
        if not state or state.get("status") != "waiting_question":
            return
        
        context = state.get("question", {}).get("context", {})
        pending_args = state.get("pending_args", {})
        
        # Обрабатываем ответ в зависимости от типа вопроса
        if context.get("type") == "column_mapping":
            # Парсим ответ пользователя (ожидаем "подразделение: Отдел, сумма: Сумма")
            mapping = self._parse_column_mapping(answer, context.get("columns", []))
            if not mapping:
                # Если не удалось разобрать – задаём повторный вопрос
                await self.session_manager.update_session(task_id, {
                    "status": "waiting_question",
                    "question": {
                        "text": "Не удалось разобрать ваш ответ. Укажите в формате: подразделение: название_колонки, сумма: название_колонки",
                        "context": context
                    },
                    "pending_args": pending_args
                })
                return
            # Сохраняем маппинг в памяти (SQLite)
            await self.memory_store.save_column_mapping(mapping)
            # Обновляем pending_args, добавляя user_mapping
            pending_args["user_mapping"] = mapping
            # Сохраняем в состояние, чтобы при следующем цикле использовать
            await self.session_manager.update_session(task_id, {
                "user_mapping": mapping,
                "pending_args": pending_args,
                "status": "processing"  # возвращаем в обработку
            })
            # Повторно запускаем цикл
            await self.run_agent_cycle(task_id)
        else:
            # Другие типы вопросов (например, уточнение правил) – пока заглушка
            await self.session_manager.update_session(task_id, {
                "status": "processing",
                "pending_args": pending_args
            })
            await self.run_agent_cycle(task_id)

    def _parse_column_mapping(self, answer: str, available_columns: List[str]) -> Optional[Dict[str, str]]:
        """Парсит ответ пользователя вида 'подразделение: Отдел, сумма: Сумма'"""
        mapping = {}
        parts = [p.strip() for p in answer.split(',')]
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                # Проверяем, что такая колонка существует
                if value in available_columns or any(value.lower() in col.lower() for col in available_columns):
                    if 'подраздел' in key or 'отдел' in key:
                        mapping['subdivision'] = value
                    elif 'сум' in key or 'стоим' in key:
                        mapping['amount'] = value
                    elif 'контрагент' in key or 'клиент' in key:
                        mapping['contractor'] = value
                    elif 'ндс' in key:
                        mapping['vat'] = value
                    elif 'сотрудник' in key or 'фио' in key:
                        mapping['employee'] = value
                    elif 'тип' in key or 'вид' in key:
                        mapping['type'] = value
        if mapping.get('subdivision') and mapping.get('amount'):
            return mapping
        return None

    async def _set_error(self, task_id: str, error_message: str):
        await self.session_manager.update_session(task_id, {
            "status": "error",
            "error": error_message
        })