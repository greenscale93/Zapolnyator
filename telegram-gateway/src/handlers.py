import os
import logging
from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiofiles import open as aio_open
from src.client import OrchestratorClient

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("start", "help"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Отправьте мне два файла:\n"
        "1. Excel-отчёт (шаблон)\n"
        "2. MXL-выгрузку из 1С\n\n"
        "Вы можете отправить их одновременно (одним сообщением) или по очереди."
    )

@router.message(Command("reset", "start"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Состояние сброшено. Можете загружать файлы заново.")

@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    doc = message.document
    file_name = doc.file_name or "unknown"
    ext = os.path.splitext(file_name)[1].lower()

    # Получаем текущие сохранённые данные
    data = await state.get_data()
    excel_path = data.get("excel_path")
    mxl_path = data.get("mxl_path")

    # Если оба уже есть – не даём загрузить ещё
    if excel_path and mxl_path:
        await message.answer("Вы уже загрузили оба файла. Начинаю обработку...")
         # Вызываем Orchestrator
        client = OrchestratorClient()
        task_id = await client.create_task(
            user_id=message.from_user.id,
            excel_path=excel_path,
            mxl_path=mxl_path,
            month="Май",  # пока захардкодим, позже можно спросить у пользователя
            year=2026
        )
        await message.answer(f"Задача создана (ID: {task_id}). Ожидайте обработку...")
        await state.clear()
        return

    # Обработка Excel-файла
    if ext in ['.xlsx', '.xls']:
        if excel_path:
            await message.answer("Excel-файл уже был загружен. Если хотите заменить, отправьте новый.")
            return
        file_path = await save_document(doc, "excel")
        await state.update_data(excel_path=file_path)
        await message.answer(f"✅ Excel-файл «{file_name}» сохранён.")

    # Обработка MXL-файла
    elif ext == '.mxl':
        if mxl_path:
            await message.answer("MXL-файл уже был загружен. Если хотите заменить, отправьте новый.")
            return
        file_path = await save_document(doc, "mxl")
        await state.update_data(mxl_path=file_path)
        await message.answer(f"✅ MXL-файл «{file_name}» сохранён.")

    else:
        await message.answer("Неизвестный формат. Пожалуйста, отправьте Excel (.xlsx/.xls) или MXL (.mxl) файл.")
        return

    # Проверяем, загружены ли оба файла
    data = await state.get_data()
    if data.get("excel_path") and data.get("mxl_path"):
        await message.answer("✅ Оба файла успешно загружены на сервер!")
        await message.answer(f"Excel: {data['excel_path']}\nMXL: {data['mxl_path']}")
        # Здесь будет вызов Orchestrator
        await state.clear()
        await message.answer("Файлы готовы к дальнейшей обработке.")
    else:
        # Если чего-то не хватает – напоминаем
        if not data.get("excel_path"):
            await message.answer("Ожидаю Excel-файл (.xlsx/.xls).")
        if not data.get("mxl_path"):
            await message.answer("Ожидаю MXL-файл (.mxl).")

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

def register_handlers(dp):
    dp.include_router(router)