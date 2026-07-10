import os
import logging
import asyncio
import json
from aiogram import Router, F, types, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, FSInputFile
from aiofiles import open as aio_open
from src.client import OrchestratorClient

router = Router()
logger = logging.getLogger(__name__)

# === НАСТРОЙКИ АВТОТЕСТА ===
AUTO_TEST = os.getenv("AUTO_TEST", "false").lower() == "true"
TEMP_DIR = os.getenv("TEMP_DIR", "/app/temp")
LAST_FILES_PATH = os.path.join(TEMP_DIR, "last_files.json")
AUTO_START_CHAT_ID = os.getenv("AUTO_START_CHAT_ID")
if AUTO_START_CHAT_ID:
    AUTO_START_CHAT_ID = int(AUTO_START_CHAT_ID)

class WaitingState(StatesGroup):
    answer = State()

def _save_last_files(excel_path: str, data_path: str):
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        with open(LAST_FILES_PATH, 'w') as f:
            json.dump({"excel": excel_path, "data": data_path}, f)
        logger.info(f"Saved last files: {excel_path}, {data_path}")
    except Exception as e:
        logger.warning(f"Could not save last files: {e}")

def _get_last_files():
    try:
        if os.path.exists(LAST_FILES_PATH):
            with open(LAST_FILES_PATH, 'r') as f:
                data = json.load(f)
            return data.get("excel"), data.get("data")
    except Exception as e:
        logger.warning(f"Could not read last files: {e}")
    return None, None

@router.message(Command("start", "help"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    if AUTO_TEST:
        excel_path, data_path = _get_last_files()
        if excel_path and data_path and os.path.exists(excel_path) and os.path.exists(data_path):
            await message.answer("🔄 Автотест: использую последние файлы...")
            await state.update_data(excel_path=excel_path, data_path=data_path)
            await start_processing(message, state, excel_path, data_path)
            return
        else:
            await message.answer("⚠️ Автотест включён, но сохранённые файлы не найдены. Отправьте файлы вручную.")
    
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
    _save_last_files(excel_path, data_path)
    client = OrchestratorClient()
    try:
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
    temp_dir = TEMP_DIR
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

# === АВТОМАТИЧЕСКИЙ ЗАПУСК ПОСЛЕ СТАРТА БОТА ===
async def auto_start_processing(bot: Bot):
    """Автоматически запускает обработку через 5 секунд после старта бота, если включён AUTO_TEST и задан AUTO_START_CHAT_ID."""
    if not AUTO_TEST:
        return
    if not AUTO_START_CHAT_ID:
        logger.warning("AUTO_TEST включён, но AUTO_START_CHAT_ID не задан. Автозапуск отключён.")
        return
    await asyncio.sleep(5)
    logger.info(f"Автоматический запуск обработки для chat_id={AUTO_START_CHAT_ID}")
    excel_path, data_path = _get_last_files()
    if not excel_path or not data_path:
        logger.warning("Нет сохранённых файлов для автозапуска.")
        await bot.send_message(AUTO_START_CHAT_ID, "⚠️ Нет сохранённых файлов для автозапуска. Отправьте файлы вручную.")
        return
    if not os.path.exists(excel_path) or not os.path.exists(data_path):
        logger.warning("Сохранённые файлы не существуют.")
        await bot.send_message(AUTO_START_CHAT_ID, "⚠️ Сохранённые файлы не найдены на сервере. Отправьте файлы вручную.")
        return
    
    # Создаём задачу напрямую через клиент
    client = OrchestratorClient()
    try:
        month = "Май"
        year = 2026
        task_id = await client.create_task(
            user_id=AUTO_START_CHAT_ID,
            excel_path=excel_path,
            data_path=data_path,
            month=month,
            year=year
        )
        await bot.send_message(AUTO_START_CHAT_ID, f"✅ Автоматически создана задача (ID: {task_id}). Начинаю обработку...")
        # Запускаем опрос статуса — для этого нужен объект Message и State. Создадим фейковый Message.
        # Создаём фейковое сообщение для использования с poll_task_status
        fake_message = types.Message(
            message_id=0,
            date=0,
            chat=types.Chat(id=AUTO_START_CHAT_ID, type="private"),
            from_user=types.User(id=AUTO_START_CHAT_ID, is_bot=False, first_name="AutoTest"),
            text="/start",
            bot=bot
        )
        # Создаём временное состояние (хранилище в памяти)
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()
        from aiogram.fsm.context import FSMContext
        from aiogram.dispatcher.dispatcher import Dispatcher
        dp = Dispatcher(storage=storage)
        state = FSMContext(dp, storage=storage, key=AUTO_START_CHAT_ID)
        # Сохраняем task_id в состояние
        await state.update_data(task_id=task_id)
        # Запускаем опрос статуса
        asyncio.create_task(poll_task_status(fake_message, state, task_id))
    except Exception as e:
        await bot.send_message(AUTO_START_CHAT_ID, f"❌ Ошибка автоматического запуска: {str(e)}")