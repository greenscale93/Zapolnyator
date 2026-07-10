import os
import logging
import asyncio
import json
import re
from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiofiles import open as aio_open
from src.client import OrchestratorClient

router = Router()
logger = logging.getLogger(__name__)

TEMP_DIR = os.getenv("TEMP_DIR", "/app/temp")
LAST_FILES_PATH = os.path.join(TEMP_DIR, "last_files.json")

class WaitingState(StatesGroup):
    answer = State()

# === Главное меню ===
def main_keyboard():
    kb = [
        [KeyboardButton(text="/autotest")],
        [KeyboardButton(text="/edit_mapping")],
        [KeyboardButton(text="/reset"), KeyboardButton(text="/stop")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def _save_last_files(excel_path: str, data_path: str):
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        with open(LAST_FILES_PATH, 'w') as f:
            json.dump({"excel": excel_path, "data": data_path}, f)
    except Exception as e:
        logger.warning(f"Could not save last files: {e}")

def _get_last_files():
    try:
        if os.path.exists(LAST_FILES_PATH):
            with open(LAST_FILES_PATH, 'r') as f:
                data = json.load(f)
            return data.get("excel"), data.get("data")
    except:
        pass
    return None, None

def extract_month_year_from_filename(filename: str) -> tuple:
    pattern = r'ВыгрузкаДляExcel[_\-]?(\d{4})[-_](\d{2})'
    match = re.search(pattern, filename)
    if match:
        year = int(match.group(1))
        month_num = int(match.group(2))
        months_ru = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }
        month_name = months_ru.get(month_num, "Май")
        return month_name, year
    return "Май", 2026

@router.message(Command("start", "help"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    client = OrchestratorClient()
    user_id = message.from_user.id
    auto_test = await client.get_autotest_status(user_id)
    if auto_test:
        excel_path, data_path = _get_last_files()
        if excel_path and data_path and os.path.exists(excel_path) and os.path.exists(data_path):
            await message.answer("🔄 Автотест включён: использую последние файлы...", reply_markup=main_keyboard())
            await state.update_data(excel_path=excel_path, data_path=data_path)
            await start_processing(message, state, excel_path, data_path)
            return
        else:
            await message.answer("⚠️ Автотест включён, но сохранённые файлы не найдены. Отправьте файлы вручную.", reply_markup=main_keyboard())
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
        await message.answer(f"🔄 Автотест {'включён' if new_status else 'выключен'}", reply_markup=main_keyboard())
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

async def start_processing(message: Message, state: FSMContext, excel_path: str, data_path: str):
    _save_last_files(excel_path, data_path)
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
    await state.update_data(task_id=task_id)
    await message.answer(f"✅ Задача создана (ID: {task_id}). Обработка...")
    asyncio.create_task(poll_task_status(message, state, task_id))

async def poll_task_status(message: Message, state: FSMContext, task_id: str):
    client = OrchestratorClient()
    while True:
        try:
            status = await client.get_task_status(task_id)
        except Exception as e:
            await message.answer(f"❌ Ошибка статуса: {str(e)}")
            break

        if status["status"] == "done":
            file_url = status.get("result", {}).get("file_url")
            if file_url:
                try:
                    file = FSInputFile(file_url)
                    await message.answer_document(file, caption="📁 Готовый отчёт")
                except Exception as e:
                    await message.answer(f"❌ Ошибка отправки файла: {str(e)}")
            await message.answer("✅ Обработка завершена.")
            await state.clear()
            break

        elif status["status"] == "error":
            await message.answer(f"❌ Ошибка: {status.get('error')}")
            await state.clear()
            break

        elif status["status"] == "waiting_question":
            question = status.get("question")
            if question and question.get("type") == "vz_office_mapping":
                # Оркестратор уже отправил сообщение с кнопками, ничего не делаем
                pass
            else:
                # Обычный текстовый вопрос
                question_text = question.get("text", "Уточните, пожалуйста.")
                await state.update_data(waiting_question=question)
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

# === ОБРАБОТЧИК INLINE-КНОПОК (CALLBACK) ===
@router.callback_query()
async def handle_callback(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    client = OrchestratorClient()

    if data.startswith("map_office|"):
        task_id = (await state.get_data()).get("task_id")
        if not task_id:
            await callback.answer("Нет активной задачи", show_alert=True)
            return
        # Отправляем ответ в оркестратор
        await client.answer_question(task_id, data)
        # Убираем кнопки, чтобы не нажимали повторно
        await callback.message.edit_reply_markup()
        await callback.answer("Выбор сохранён")
        # Перезапускаем мониторинг задачи (могут быть ещё вопросы или завершение)
        asyncio.create_task(poll_task_status(callback.message, state, task_id))
        return

    elif data.startswith("del_mapping|"):
        contractor = data.split("|")[1]
        task_id = (await state.get_data()).get("task_id", "dummy")
        await client.delete_mapping(task_id, contractor)
        # Убираем удалённую кнопку из списка
        new_markup = remove_button(callback.message.reply_markup, contractor)
        await callback.message.edit_reply_markup(reply_markup=new_markup)
        await callback.answer("Маппинг удалён")

    elif data == "edit_mapping_cancel":
        await callback.message.edit_reply_markup()
        await callback.answer("Отменено")

def remove_button(markup: InlineKeyboardMarkup, contractor: str) -> InlineKeyboardMarkup:
    new_rows = []
    for row in markup.inline_keyboard:
        new_buttons = [btn for btn in row if not btn.callback_data.startswith(f"del_mapping|{contractor}")]
        if new_buttons:
            new_rows.append(new_buttons)
    return InlineKeyboardMarkup(inline_keyboard=new_rows)

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