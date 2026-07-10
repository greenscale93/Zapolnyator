import os
import logging
import asyncio
from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, FSInputFile
from aiofiles import open as aio_open
from src.client import OrchestratorClient

router = Router()
logger = logging.getLogger(__name__)

class WaitingState(StatesGroup):
    answer = State()

@router.message(Command("start", "help"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Отправьте мне два файла:\n"
        "1. Excel-отчёт (шаблон)\n"
        "2. MXL-выгрузку из 1С\n\n"
        "Вы можете отправить их одновременно (одним сообщением) или по очереди."
    )

@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Состояние сброшено. Можете загружать файлы заново.")

@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    doc = message.document
    file_name = doc.file_name or "unknown"
    ext = os.path.splitext(file_name)[1].lower()

    data = await state.get_data()
    excel_path = data.get("excel_path")
    mxl_path = data.get("mxl_path")

    if excel_path and mxl_path:
        await message.answer("Вы уже загрузили оба файла. Начинаю обработку...")
        await start_processing(message, state, excel_path, mxl_path)
        return

    if ext in ['.xlsx', '.xls']:
        if excel_path:
            await message.answer("Excel-файл уже был загружен. Если хотите заменить, отправьте новый.")
            return
        file_path = await save_document(doc, "excel")
        await state.update_data(excel_path=file_path)
        await message.answer(f"✅ Excel-файл «{file_name}» сохранён.")
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

    data = await state.get_data()
    if data.get("excel_path") and data.get("mxl_path"):
        await message.answer("✅ Оба файла успешно загружены на сервер!")
        await start_processing(message, state, data["excel_path"], data["mxl_path"])
    else:
        if not data.get("excel_path"):
            await message.answer("Ожидаю Excel-файл (.xlsx/.xls).")
        if not data.get("mxl_path"):
            await message.answer("Ожидаю MXL-файл (.mxl).")

async def start_processing(message: Message, state: FSMContext, excel_path: str, mxl_path: str):
    client = OrchestratorClient()
    try:
        task_id = await client.create_task(
            user_id=message.from_user.id,
            excel_path=excel_path,
            mxl_path=mxl_path,
            month="Май",
            year=2026
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании задачи: {str(e)}")
        await state.clear()
        return

    await message.answer(f"✅ Задача создана (ID: {task_id}). Начинаю обработку...")
    await state.update_data(task_id=task_id)
    asyncio.create_task(poll_task_status(message, state, task_id))

async def poll_task_status(message: Message, state: FSMContext, task_id: str):
    client = OrchestratorClient()
    while True:
        try:
            status = await client.get_task_status(task_id)
        except Exception as e:
            await message.answer(f"❌ Ошибка получения статуса: {str(e)}")
            break

        if status["status"] == "done":
            result = status.get("result", {})
            file_url = result.get("file_url")
            metrics = result.get("metrics", {})
            await message.answer("✅ Обработка завершена успешно!")
            if file_url:
                try:
                    file = FSInputFile(file_url)
                    await message.answer_document(file, caption="📁 Заполненный отчёт")
                except Exception as e:
                    await message.answer(f"❌ Не удалось отправить файл: {str(e)}")
            if metrics:
                await message.answer(f"📊 Показатели: {metrics}")
            await state.clear()
            break

        elif status["status"] == "error":
            error = status.get("error", "Неизвестная ошибка")
            await message.answer(f"❌ Ошибка обработки: {error}")
            await state.clear()
            break

        elif status["status"] == "waiting_question":
            question_data = status.get("question", {})
            question_text = question_data.get("text", "Уточните, пожалуйста.")
            await state.update_data(waiting_question=question_data)
            await message.answer(f"❓ {question_text}")
            await state.set_state(WaitingState.answer)
            break

        await asyncio.sleep(2)

@router.message(StateFilter(WaitingState.answer), F.text)
async def handle_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id:
        await message.answer("❌ Не найден идентификатор задачи. Попробуйте начать заново.")
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
    asyncio.create_task(poll_task_status(message, state, task_id))

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