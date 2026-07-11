"""
Обработчики команд: /start, /reset, /autotest, /stop, /edit_mapping.
"""
import os
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from src.client import OrchestratorClient
from src.utils.file_storage import get_last_files
from .polling import start_processing

logger = logging.getLogger(__name__)

router = Router()


def main_keyboard():
    """Стандартная клавиатура с основными командами."""
    kb = [
        [KeyboardButton(text="/autotest")],
        [KeyboardButton(text="/edit_mapping")],
        [KeyboardButton(text="/reset"), KeyboardButton(text="/stop")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


@router.message(Command("start", "help"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    client = OrchestratorClient()
    user_id = message.from_user.id
    auto_test = await client.get_autotest_status(user_id)
    if auto_test:
        excel_path, data_path = get_last_files()
        if excel_path and data_path and os.path.exists(excel_path) and os.path.exists(data_path):
            await message.answer(
                "🔄 Автотест включён: использую последние файлы...",
                reply_markup=main_keyboard()
            )
            await state.update_data(excel_path=excel_path, data_path=data_path)
            await start_processing(message, state, excel_path, data_path)
            return
        else:
            await message.answer(
                "⚠️ Автотест включён, но сохранённые файлы не найдены. "
                "Отправьте файлы вручную.",
                reply_markup=main_keyboard()
            )
    else:
        await message.answer(
            "Привет! Отправьте два файла или используйте команды.",
            reply_markup=main_keyboard()
        )


@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Состояние сброшено.", reply_markup=main_keyboard())


@router.message(Command("autotest"))
async def cmd_autotest(message: Message, state: FSMContext):
    client = OrchestratorClient()
    user_id = message.from_user.id
    try:
        current = await client.get_autotest_status(user_id)
        new_status = not current
        await client.set_autotest_status(user_id, new_status)
        await message.answer(
            f"🔄 Автотест {'включён' if new_status else 'выключен'}",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")


@router.message(Command("stop"))
async def cmd_stop(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    if task_id:
        client = OrchestratorClient()
        await client.stop_task(task_id)
        await state.clear()
        await message.answer("🛑 Задача остановлена.", reply_markup=main_keyboard())
    else:
        await message.answer("Нет активной задачи.")


@router.message(Command("edit_mapping"))
async def cmd_edit_mapping(message: Message):
    client = OrchestratorClient()
    await client.edit_mapping(message.from_user.id)
    await message.answer("Запрошено редактирование маппинга.")
