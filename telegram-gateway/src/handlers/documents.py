"""
Обработчики загрузки документов: приём Excel/MXL файлов, сохранение.
"""
import os
import logging
import aiofiles
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Document

from src.utils.file_storage import extract_month_year_from_filename
from .polling import start_processing

logger = logging.getLogger(__name__)

router = Router()


async def save_document(doc: Document, prefix: str) -> str:
    """Сохраняет документ во временную директорию и возвращает путь."""
    temp_dir = os.getenv("TEMP_DIR", "/app/temp")
    os.makedirs(temp_dir, exist_ok=True)
    file_id = doc.file_id
    file_name = f"{prefix}_{file_id}.{doc.file_name.split('.')[-1]}"
    file_path = os.path.join(temp_dir, file_name)
    file_info = await doc.bot.get_file(file_id)
    downloaded_file = await doc.bot.download_file(file_info.file_path)
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(downloaded_file.read())
    return file_path


@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    doc = message.document
    file_name = doc.file_name or "unknown"
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in ['.xlsx', '.xls', '.mxl']:
        await message.answer("❌ Неподдерживаемый формат.")
        return

    data = await state.get_data()
    excel_path = data.get("excel_path")
    data_path = data.get("data_path")

    if excel_path and data_path:
        await message.answer("Оба файла уже загружены, начинаю обработку...")
        await start_processing(message, state, excel_path, data_path)
        return

    if "ВыгрузкаДляExcel" in file_name or "выгрузкадляexcel" in file_name.lower():
        if data_path:
            await message.answer("Файл данных уже загружен.")
            return
        file_path = await save_document(doc, "data")
        await state.update_data(data_path=file_path)
        month, year = extract_month_year_from_filename(file_name)
        await state.update_data(month=month, year=year)
        await message.answer(f"✅ Данные сохранены (месяц: {month}, год: {year}).")
    else:
        if excel_path:
            await message.answer("Шаблон уже загружен.")
            return
        if ext not in ['.xlsx', '.xls']:
            await message.answer("❌ Шаблон должен быть Excel.")
            return
        file_path = await save_document(doc, "excel")
        await state.update_data(excel_path=file_path)
        await message.answer("✅ Шаблон сохранён.")

    data = await state.get_data()
    if data.get("excel_path") and data.get("data_path"):
        await message.answer("✅ Оба файла загружены. Запускаю обработку...")
        await start_processing(message, state, data["excel_path"], data["data_path"])
