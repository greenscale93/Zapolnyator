import logging
import os
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

    async def process_answer(self, task_id: str, answer: str):
        # Получить состояние
        state = await self.session_manager.get_session(task_id)
        if not state:
            return
        # Сохранить ответ пользователя как новое правило в памяти
        # (здесь будет логика извлечения правила из ответа)
        # Упрощённо: сохраняем в память и перезапускаем обработку
        # Пока просто сохраним в памяти и переведём статус обратно в processing
        await self.memory_store.save_rule(state.get("clarification_context"), answer)
        await self.session_manager.update_session(task_id, {"status": "processing"})
        # Запустить цикл обработки заново
        await self.run_agent_cycle(task_id)

    async def run_agent_cycle(self, task_id: str):
        state = await self.session_manager.get_session(task_id)
        # Здесь полный цикл: вызывать DeepSeek, выполнять инструменты через Worker, обрабатывать ошибки и т.д.
        # Пока заглушка – просто переводим в done с фиктивными данными
        # В реальности нужно вызывать DeepSeek, парсить ответ, вызывать функции и т.д.
        # Мы реализуем это позже, когда появится Worker.
        await self.session_manager.update_session(task_id, {
            "status": "done",
            "result_file": "/tmp/done.xlsx",
            "metrics": {"test": 123}
        })