from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
import logging
import asyncio
from typing import Dict

from src.agent import OrchestratorAgent
from src.session_manager import SessionManager
from src.memory import MemoryStore
from src.worker_client import WorkerClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

session_manager = SessionManager()
memory_store = MemoryStore()
worker_client = WorkerClient()
agent = OrchestratorAgent(session_manager, memory_store, worker_client)

class TaskCreateRequest(BaseModel):
    user_id: int
    files: Dict[str, str]
    month: str
    year: int

class TaskAnswerRequest(BaseModel):
    answer: str

@router.post("/task")
async def create_task(request: TaskCreateRequest):
    if "excel" not in request.files or "data" not in request.files:
        raise HTTPException(status_code=400, detail="Missing file keys: 'excel' and 'data' are required")
    task_id = str(uuid.uuid4())
    logger.info(f"Создана задача {task_id} для пользователя {request.user_id}")
    logger.info(f"Шаблон: {request.files['excel']}, Данные: {request.files['data']}")
    await session_manager.init_session(
        task_id,
        request.user_id,
        request.files,
        request.month,
        request.year
    )
    asyncio.create_task(agent.run_agent_cycle(task_id))
    return {"task_id": task_id, "status": "accepted"}

@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    state = await session_manager.get_session(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
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
    await agent.process_answer(task_id, request.answer)
    return {"status": "ok"}

@router.post("/task/{task_id}/stop")
async def stop_task(task_id: str):
    logger.info(f"Received stop for task {task_id}")
    await agent.stop_task(task_id)
    return {"status": "ok"}