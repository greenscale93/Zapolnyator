"""
Обработчики callback-запросов от inline-кнопок:
- map_office|contractor|idx — выбор офиса для контрагента
- del_mapping|contractor — удаление маппинга
- edit_mapping_cancel — отмена редактирования
"""
import logging
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup

from src.client import OrchestratorClient
from .polling import start_polling_if_needed

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query()
async def handle_callback(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    client = OrchestratorClient()

    if data.startswith("map_office|"):
        task_id = (await state.get_data()).get("task_id")
        if not task_id:
            await callback.answer("Нет активной задачи", show_alert=True)
            return
        await client.answer_question(task_id, data)
        await callback.message.edit_reply_markup()
        await callback.answer("Выбор сохранён")
        await start_polling_if_needed(callback.message, state, task_id)
        return

    elif data.startswith("del_mapping|"):
        contractor = data.split("|")[1]
        task_id = (await state.get_data()).get("task_id", "dummy")
        await client.delete_mapping(task_id, contractor)
        new_markup = remove_button(callback.message.reply_markup, contractor)
        await callback.message.edit_reply_markup(reply_markup=new_markup)
        await callback.answer("Маппинг удалён")

    elif data == "edit_mapping_cancel":
        await callback.message.edit_reply_markup()
        await callback.answer("Отменено")


def remove_button(
    markup: InlineKeyboardMarkup,
    contractor: str
) -> InlineKeyboardMarkup:
    """Удаляет кнопку для указанного контрагента из клавиатуры."""
    new_rows = []
    for row in markup.inline_keyboard:
        new_buttons = [
            btn for btn in row
            if not btn.callback_data.startswith(f"del_mapping|{contractor}")
        ]
        if new_buttons:
            new_rows.append(new_buttons)
    return InlineKeyboardMarkup(inline_keyboard=new_rows)
