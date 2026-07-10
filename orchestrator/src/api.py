from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
import logging
from typing import Optional, Dict, Any

from src.agent import OrchestratorAgent
from src.session_manager import SessionManager
from src.memory import MemoryStore
from src.worker_client import WorkerClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

# Инициализация зависимостей (пока глобально, потом можно через Depends)
session_manager = SessionManager()
memory_store = MemoryStore()
worker_client = WorkerClient()
agent = OrchestratorAgent(session_manager, memory_store, worker_client)

class TaskCreateRequest(BaseModel):
    user_id: int
    files: Dict[str, str]  # {"excel": "/path/to/file.xlsx", "mxl": "/path/to/file.mxl"}
    month: str
    year: int

class TaskAnswerRequest(BaseModel):
    answer: str

@router.post("/task")
async def create_task(request: TaskCreateRequest):
    task_id = str(uuid.uuid4())
    logger.info(f"Создана задача {task_id} для пользователя {request.user_id}")
    
    # Сохраняем начальное состояние
    await session_manager.init_session(task_id, request.user_id, request.files, request.month, request.year)
    
    # Запускаем обработку асинхронно (в фоне) – но для простоты мы пока синхронно, но с быстрым возвратом
    # Мы вернём task_id, а статус можно будет получить по GET /task/{task_id}
    # Здесь мы просто инициируем обработку в фоне через asyncio.create_task, но для начала сделаем синхронно?
    # Чтобы не блокировать ответ, лучше запустить в фоне. Реализуем позже.
    # Пока вернём принято.
    return {"task_id": task_id, "status": "accepted"}

@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    state = await session_manager.get_session(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    # Преобразуем состояние в нужный формат
    response = {
        "task_id": task_id,
        "status": state.get("status", "processing"),
    }
    if state.get("status") == "waiting_question":
        response["question"] = state.get("question")
    if state.get("status") == "done":
        response["result"] = {
            "file_url": state.get("result_file"),
            "metrics": state.get("metrics")
        }
    if state.get("error"):
        response["error"] = state.get("error")
    return response

@router.post("/task/{task_id}/answer")
async def answer_question(task_id: str, request: TaskAnswerRequest):
    state = await session_manager.get_session(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    if state.get("status") != "waiting_question":
        raise HTTPException(status_code=400, detail="Not waiting for question")
    # Передаём ответ в агент
    await agent.process_answer(task_id, request.answer)
    return {"status": "ok"}