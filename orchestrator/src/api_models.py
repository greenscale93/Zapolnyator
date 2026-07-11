"""
Pydantic модели для API orchestrator-сервиса.

Извлечены из api.py для уменьшения размера модуля.
"""
from pydantic import BaseModel


class CreateTaskRequest(BaseModel):
    user_id: int
    files: dict
    month: str = "Май"
    year: int = 2026


class AnswerRequest(BaseModel):
    answer: str


class EditMappingRequest(BaseModel):
    user_id: int


class DeleteMappingRequest(BaseModel):
    task_id: str
    contractor: str
