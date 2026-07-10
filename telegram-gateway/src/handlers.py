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
        "1. Шаблон отчёта (Excel) – например, 'ДКП 10 - май 2026.xlsx'\n"
        "2. Выгрузка данных (Excel) – имя должно содержать 'ВыгрузкаДляExcel'\n\n"
        "Вы можете отправлять их в любом порядке."
    )

@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Состояние сброшено. Можете загружать файлы заново.")

@router.message(Command("stop"))
async def cmd_stop(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id:
        await message.answer("❌ Нет активной задачи для остановки.")
        return
    client = OrchestratorClient()
    try:
        await client.stop_task(task_id)
        await message.answer("⏹️ Задача остановлена.")
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    doc = message.document
    file_name = doc.file_name or "unknown"
    ext = os.path.splitext(file_name)[1].lower()

    if ext not in ['.xlsx', '.xls', '.mxl']:
        await message.answer("❌ Неподдерживаемый формат. Отправьте Excel (.xlsx/.xls) или MXL (.mxl).")
        return

    data = await state.get_data()
    excel_path = data.get("excel_path")
    data_path = data.get("data_path")

    if excel_path and data_path:
        await message.answer("Вы уже загрузили оба файла. Начинаю обработку...")
        await start_processing(message, state, excel_path, data_path)
        return

    if "ВыгрузкаДляExcel" in file_name or "выгрузкадляexcel" in file_name.lower():
        if data_path:
            await message.answer("Файл с данными уже загружен. Если хотите заменить, отправьте новый.")
            return
        file_path = await save_document(doc, "data")
        await state.update_data(data_path=file_path)
        await message.answer(f"✅ Файл с данными «{file_name}» сохранён.")
        if not excel_path:
            await message.answer("Ожидаю шаблон Excel (например, 'ДКП 10 - май 2026.xlsx').")
    else:
        if excel_path:
            await message.answer("Шаблон отчёта уже загружен. Если хотите заменить, отправьте новый.")
            return
        if ext not in ['.xlsx', '.xls']:
            await message.answer("❌ Шаблон должен быть в формате Excel (.xlsx/.xls).")
            return
        file_path = await save_document(doc, "excel")
        await state.update_data(excel_path=file_path)
        await message.answer(f"✅ Шаблон отчёта «{file_name}» сохранён.")
        if not data_path:
            await message.answer("Ожидаю файл с данными (содержит 'ВыгрузкаДляExcel').")

    data = await state.get_data()
    if data.get("excel_path") and data.get("data_path"):
        await message.answer("✅ Оба файла успешно загружены на сервер!")
        await start_processing(message, state, data["excel_path"], data["data_path"])

async def start_processing(message: Message, state: FSMContext, excel_path: str, data_path: str):
    client = OrchestratorClient()
    try:
        # Извлекаем месяц и год из имени шаблона (упрощённо)
        month = "Май"
        year = 2026
        task_id = await client.create_task(
            user_id=message.from_user.id,
            excel_path=excel_path,
            data_path=data_path,
            month=month,
            year=year
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