import os
import uuid
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from src.session_manager import SessionManager
from src.memory import MemoryStore
from src.worker_client import WorkerClient
from src.agent import OrchestratorAgent

router = APIRouter()

# Глобальные объекты (можно заменить на DI, но пока так)
session_manager = SessionManager()
memory_store = MemoryStore()
worker_client = WorkerClient()
agent = OrchestratorAgent(session_manager, memory_store, worker_client)

class CreateTaskRequest(BaseModel):
    user_id: int
    files: dict  # {"excel": path, "data": path}
    month: str = "Май"
    year: int = 2026

class AnswerRequest(BaseModel):
    answer: str

class EditMappingRequest(BaseModel):
    user_id: int

class DeleteMappingRequest(BaseModel):
    task_id: str
    contractor: str

# ================== ЗАДАЧИ ==================

@router.post("/api/v1/task")
async def create_task(request: CreateTaskRequest):
    task_id = str(uuid.uuid4())
    await session_manager.create_session(task_id, {
        "user_id": request.user_id,
        "files": request.files,
        "month": request.month,
        "year": request.year,
        "status": "running"
    })
    # Запускаем обработку в фоне
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

# ================== АВТОТЕСТ ==================

@router.get("/api/v1/autotest/status/{user_id}")
async def get_autotest_status(user_id: int):
    enabled = await session_manager.get_autotest(user_id)
    return {"enabled": enabled}

@router.post("/api/v1/autotest/toggle/{user_id}")
async def toggle_autotest(user_id: int):
    current = await session_manager.get_autotest(user_id)
    new_status = not current
    await session_manager.set_autotest(user_id, new_status)
    return {"enabled": new_status}

# ================== МАППИНГ (НОВЫЕ) ==================

@router.post("/api/v1/edit_mapping")
async def edit_mapping(request: EditMappingRequest):
    await agent.edit_mapping_command(request.user_id)
    return {"status": "ok"}

@router.post("/api/v1/delete_mapping")
async def delete_mapping(request: DeleteMappingRequest):
    await agent.handle_delete_mapping(request.task_id, request.contractor)
    return {"status": "ok"}