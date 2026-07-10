import os
import logging
from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiofiles import open as aio_open

router = Router()
logger = logging.getLogger(__name__)

class FileStates(StatesGroup):
    waiting_excel = State()
    waiting_mxl = State()

@router.message(Command("start", "help"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Отправьте мне два файла:\n"
        "1. Excel-отчёт (шаблон)\n"
        "2. MXL-выгрузку из 1С\n\n"
        "Вы можете отправить их одновременно (одним сообщением) или по очереди."
    )
    await state.set_state(FileStates.waiting_excel)

@router.message(StateFilter(FileStates.waiting_excel), F.document)
@router.message(StateFilter(FileStates.waiting_mxl), F.document)
async def handle_document(message: Message, state: FSMContext):
    current_state = await state.get_state()
    doc = message.document
    file_name = doc.file_name or "unknown"
    ext = os.path.splitext(file_name)[1].lower()

    if current_state == FileStates.waiting_excel:
        if ext not in ['.xlsx', '.xls']:
            await message.answer("Пожалуйста, отправьте Excel-файл (.xlsx или .xls).")
            return
        file_path = await save_document(doc, "excel")
        await state.update_data(excel_path=file_path)
        await message.answer(f"Excel-файл «{file_name}» сохранён.")
        await state.set_state(FileStates.waiting_mxl)
        await message.answer("Теперь отправьте MXL-файл (выгрузка из 1С).")
    elif current_state == FileStates.waiting_mxl:
        if ext != '.mxl':
            await message.answer("Пожалуйста, отправьте MXL-файл (расширение .mxl).")
            return
        file_path = await save_document(doc, "mxl")
        await state.update_data(mxl_path=file_path)
        await message.answer(f"MXL-файл «{file_name}» сохранён.")
        data = await state.get_data()
        excel_path = data.get("excel_path")
        mxl_path = data.get("mxl_path")
        if excel_path and mxl_path:
            await message.answer("✅ Оба файла успешно загружены на сервер!")
            await message.answer(f"Excel: {excel_path}\nMXL: {mxl_path}")
            # Здесь в будущем будет вызов Orchestrator
            await state.clear()
            await message.answer("Файлы готовы к дальнейшей обработке.")
        else:
            await state.set_state(FileStates.waiting_excel)
            await message.answer("Что-то пошло не так, начнём заново. Отправьте Excel-файл.")

async def save_document(doc: types.Document, prefix: str) -> str:
    temp_dir = os.getenv("TEMP_DIR", "/app/temp")
    os.makedirs(temp_dir, exist_ok=True)
    file_id = doc.file_id
    file_name = f"{prefix}_{file_id}.{doc.file_name.split('.')[-1]}"
    file_path = os.path.join(temp_dir, file_name)
    file_info = await doc.bot.get_file(file_id)
    downloaded_file = await doc.bot.download_file(file_info.file_path)
    async with aio_open(file_path, "wb") as f:
        await f.write(downloaded_file.read())
    return file_path