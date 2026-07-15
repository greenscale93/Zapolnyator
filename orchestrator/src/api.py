import uuid
import asyncio
from fastapi import APIRouter, HTTPException
from src.session_manager import SessionManager
from src.memory import MemoryStore
from src.worker_client import WorkerClient
from src.agent import OrchestratorAgent
from src.api_models import CreateTaskRequest, AnswerRequest, EditMappingRequest, DeleteMappingRequest
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
session_manager = SessionManager()
memory_store = MemoryStore()
worker_client = WorkerClient()
agent = OrchestratorAgent(session_manager, memory_store, worker_client)

@router.post("/api/v1/task")
async def create_task(request: CreateTaskRequest):
    task_id = str(uuid.uuid4())
    await session_manager.init_session(
        task_id=task_id,
        user_id=request.user_id,
        files=request.files,
        month=request.month,
        year=request.year
    )
    logger.info(f"Task {task_id} created, starting agent")
    asyncio.create_task(agent.run_agent_cycle(task_id))
    return {"task_id": task_id}

@router.get("/api/v1/task/{task_id}")
async def get_task_status(task_id: str):
    state = await session_manager.get_session(task_id)
    if not state:
        raise HTTPException(404, "Task not found")
    return state

@router.post("/api/v1/task/{task_id}/answer")
async def answer_question(task_id: str, request: AnswerRequest):
    await agent.handle_answer(task_id, request.answer)
    return {"status": "ok"}

@router.post("/api/v1/task/{task_id}/stop")
async def stop_task(task_id: str):
    await agent.stop_task(task_id)
    return {"status": "cancelled"}

@router.get("/api/v1/autotest/status/{user_id}")
async def get_autotest_status(user_id: int):
    enabled = await session_manager.get_auto_test_status(user_id)
    return {"enabled": enabled}

@router.post("/api/v1/autotest/toggle/{user_id}")
async def toggle_autotest(user_id: int):
    current = await session_manager.get_auto_test_status(user_id)
    new_status = not current
    await session_manager.set_auto_test_status(user_id, new_status)
    return {"enabled": new_status}

@router.get("/api/v1/diagnostic/status/{user_id}")
async def get_diagnostic_status(user_id: int):
    enabled = await session_manager.get_diagnostic_status(user_id)
    return {"enabled": enabled}

@router.post("/api/v1/diagnostic/toggle/{user_id}")
async def toggle_diagnostic(user_id: int):
    current = await session_manager.get_diagnostic_status(user_id)
    new_status = not current
    await session_manager.set_diagnostic_status(user_id, new_status)
    return {"enabled": new_status}

@router.get("/api/v1/mapping/stats/{user_id}")
async def mapping_stats(user_id: int):
    """Возвращает статистику сохранённых маппингов."""
    await agent.mapping_stats_command(user_id)
    return {"status": "ok"}

@router.post("/api/v1/edit_mapping")
async def edit_mapping(request: EditMappingRequest):
    await agent.edit_mapping_command(request.user_id)
    return {"status": "ok"}

@router.post("/api/v1/delete_mapping")
async def delete_mapping(request: DeleteMappingRequest):
    await agent.handle_delete_mapping(request.task_id, request.contractor)
    return {"status": "ok"}