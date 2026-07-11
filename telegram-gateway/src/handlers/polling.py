"""
Мониторинг статуса задачи: опрос orchestrator-сервера,
обработка состояний done / error / waiting_question.
"""
import os
import asyncio
import logging
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, FSInputFile

from src.client import OrchestratorClient
from src.utils.file_storage import save_last_files

logger = logging.getLogger(__name__)

router = Router()


async def start_processing(
    message: Message,
    state: FSMContext,
    excel_path: str,
    data_path: str
):
    """Создаёт задачу в оркестраторе и запускает мониторинг."""
    save_last_files(excel_path, data_path)
    client = OrchestratorClient()
    data = await state.get_data()
    month = data.get("month", "Май")
    year = data.get("year", 2026)
    try:
        task_id = await client.create_task(
            user_id=message.from_user.id,
            excel_path=excel_path,
            data_path=data_path,
            month=month,
            year=year
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка создания задачи: {str(e)}")
        await state.clear()
        return
    await state.update_data(task_id=task_id, polling_active=False)
    await message.answer(f"✅ Задача создана (ID: {task_id}). Обработка...")
    await start_polling_if_needed(message, state, task_id)


async def start_polling_if_needed(
    message: Message,
    state: FSMContext,
    task_id: str
):
    """Запускает мониторинг, если он ещё не активен."""
    data = await state.get_data()
    if data.get("polling_active"):
        return
    await state.update_data(polling_active=True)
    asyncio.create_task(poll_task_status(message, state, task_id))


async def poll_task_status(
    message: Message,
    state: FSMContext,
    task_id: str
):
    """Периодически опрашивает статус задачи и обрабатывает результат."""
    client = OrchestratorClient()
    while True:
        try:
            status = await client.get_task_status(task_id)
        except Exception as e:
            await message.answer(f"❌ Ошибка статуса: {str(e)}")
            await state.update_data(polling_active=False)
            break

        if status["status"] == "done":
            result = status.get("result", {})
            file_path = result.get("result_file") or status.get("result_file")
            if file_path and os.path.exists(file_path):
                try:
                    file = FSInputFile(file_path)
                    await message.answer_document(file, caption="📁 Готовый отчёт")
                except Exception as e:
                    await message.answer(f"❌ Ошибка отправки файла: {str(e)}")
            else:
                await message.answer("✅ Обработка завершена, но файл не найден.")
            await message.answer("✅ Обработка завершена.")
            await state.clear()
            break

        elif status["status"] == "error":
            await message.answer(f"❌ Ошибка: {status.get('error')}")
            await state.clear()
            await state.update_data(polling_active=False)
            break

        elif status["status"] == "waiting_question":
            question = status.get("question")
            if question and question.get("type") == "vz_office_mapping":
                # Обрабатывается в callbacks.py
                pass
            else:
                question_text = question.get("text", "Уточните, пожалуйста.")
                await state.update_data(waiting_question=question)
                await message.answer(f"❓ {question_text}")
                from .fsm import WaitingState
                await state.set_state(WaitingState.answer)
                break
        await asyncio.sleep(2)
