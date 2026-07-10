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
        
        # Системный промпт (можно вынести в отдельный файл)
        system_prompt = """
        Ты — агент, который помогает заполнять отчёт ДКП. У тебя есть доступ к инструментам:
        - parse_mxl(file_path) — парсит MXL-файл.
        - process_data(mxl_data, month, year, rules) — применяет бизнес-логику.
        - update_excel(template_path, data, month, year, password) — заполняет Excel.
        - calculate_metrics(output_path, month, year, payroll_data) — считает метрики.
        Если данные неоднозначны, запроси у пользователя уточнение через вопрос. Сохраняй новые правила в память.
        """
        
        history = state.get("history", [])
        # Добавляем системное сообщение, если оно не было добавлено ранее
        if not history or history[0].get("role") != "system":
            history.insert(0, {"role": "system", "content": system_prompt})
        
        # Получаем файлы и параметры
        files = state.get("files", {})
        month = state.get("month", "Май")
        year = state.get("year", 2026)
        
        # 1. Вызов parse_mxl
        parse_result = await self.worker_client.call_tool("parse_mxl", {"file_path": files.get("mxl")})
        if parse_result["status"] == "error":
            await self._set_error(task_id, parse_result.get("error_message"))
            return
        mxl_data = parse_result["result"]["data"]
        
        # 2. Вызов process_data
        process_result = await self.worker_client.call_tool("process_data", {
            "mxl_data": mxl_data,
            "month": month,
            "year": year,
            "rules": rules
        })
        if process_result["status"] == "error":
            await self._set_error(task_id, process_result.get("error_message"))
            return
        elif process_result["status"] == "needs_clarification":
            # Сохраняем вопрос и ждём ответа
            question = process_result["clarification"]["question"]
            context = process_result["clarification"]["context"]
            await self.session_manager.update_session(task_id, {
                "status": "waiting_question",
                "question": {"text": question, "context": context},
                "pending_tool": "process_data",
                "pending_args": {"mxl_data": mxl_data, "month": month, "year": year, "rules": rules}
            })
            return
        
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
        
        # Сохраняем новое правило в память (упрощённо)
        context = state.get("question", {}).get("context", {})
        await self.memory_store.save_rule(context, answer)
        
        # Возвращаемся к обработке
        pending_args = state.get("pending_args", {})
        # Повторно вызываем process_data с обновлёнными правилами
        rules = await self.memory_store.load_all_rules()
        pending_args["rules"] = rules
        process_result = await self.worker_client.call_tool("process_data", pending_args)
        if process_result["status"] == "error":
            await self._set_error(task_id, process_result.get("error_message"))
            return
        elif process_result["status"] == "needs_clarification":
            # Если снова нужен вопрос – обновляем и ждём
            await self.session_manager.update_session(task_id, {
                "status": "waiting_question",
                "question": {"text": process_result["clarification"]["question"], "context": process_result["clarification"]["context"]},
                "pending_args": pending_args
            })
            return
        # Если успешно – продолжаем дальше (повторяем вызов update_excel и calculate_metrics)
        # Для простоты мы перезапустим весь цикл с новыми правилами
        await self.run_agent_cycle(task_id)

    async def _set_error(self, task_id: str, error_message: str):
        await self.session_manager.update_session(task_id, {
            "status": "error",
            "error": error_message
        })