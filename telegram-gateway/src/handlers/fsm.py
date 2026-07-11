"""
FSM (Finite State Machine) состояния и обработчик ответов пользователя.
"""
import logging
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.client import OrchestratorClient
from .polling import start_polling_if_needed

logger = logging.getLogger(__name__)

router = Router()


class WaitingState(StatesGroup):
    """Состояние ожидания ответа от пользователя."""
    answer = State()


@router.message(StateFilter(WaitingState.answer), F.text)
async def handle_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id:
        await message.answer("❌ Не найден идентификатор задачи.")
        await state.clear()
        return

    client = OrchestratorClient()
    try:
        await client.answer_question(task_id, message.text)
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки ответа: {str(e)}")
        await state.clear()
        return

    await message.answer("✅ Ответ принят. Продолжаю обработку...")
    await state.set_state(None)
    await start_polling_if_needed(message, state, task_id)
