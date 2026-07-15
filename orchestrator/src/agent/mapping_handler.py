"""
Обработка маппинга офисов для взаиморасчетов.

Извлечено из agent.py для уменьшения размера модуля.
Содержит:
- построение inline-клавиатуры для выбора офиса
- обработку ответа с выбором офиса
- команды редактирования/удаления маппингов
"""
import logging
from typing import List, Callable, Optional

from src.mapping_store import (
    get_mapping_dict, set_mapping, get_all_mappings, delete_mapping, get_mapping_count
)
from src.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class MappingHandler:
    """
    Управление маппингом контрагент → офис для взаиморасчетов.

    Принимает on_cycle_complete — callback, который вызывается после
    обработки всех контрагентов для продолжения цикла агента.
    """

    def __init__(
        self,
        notifier: TelegramNotifier,
        on_cycle_complete: Optional[Callable] = None
    ):
        self.notifier = notifier
        self.on_cycle_complete = on_cycle_complete

    def build_office_keyboard(self, offices: List[str], contractor: str) -> list:
        """
        Строит клавиатуру, где callback_data содержит индекс офиса, а не полное название.
        Это решает проблему с длиной callback_data > 64 байт.
        """
        keyboard = []
        row = []
        for idx, office in enumerate(offices):
            row.append({
                "text": office,
                "callback_data": f"map_office|{contractor}|{idx}"
            })
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        # Кнопка "Чужой офис" отправляет специальный индекс -1
        keyboard.append([{
            "text": "Чужой офис",
            "callback_data": f"map_office|{contractor}|-1"
        }])
        return keyboard

    async def process_answer(
        self, answer_data: str, session_manager, task_id: str
    ):
        """
        Обрабатывает ответ пользователя с выбором офиса.
        answer_data: map_office|contractor|index
        """
        parts = answer_data.split("|")
        if len(parts) != 3 or parts[0] != "map_office":
            return
        contractor = parts[1]
        idx_str = parts[2]
        try:
            idx = int(idx_str)
        except ValueError:
            return

        state = await session_manager.get_session(task_id)
        question = state.get("question")
        offices_options = state.get("offices_options", [])
        if not question or not offices_options:
            return

        if idx == -1:
            selected_office = "Взаиморасчеты с др. офисами"
        else:
            if idx < 0 or idx >= len(offices_options):
                return
            selected_office = offices_options[idx]

        set_mapping(contractor, selected_office)

        contractors = question["contractors"]
        current_idx = question["current_idx"]
        if current_idx < len(contractors) and contractors[current_idx] == contractor:
            current_idx += 1
            if current_idx < len(contractors):
                next_contractor = contractors[current_idx]
                reply_markup = {
                    "inline_keyboard": self.build_office_keyboard(
                        offices_options, next_contractor
                    )
                }
                user_id = state["user_id"]
                await self.notifier.send_message(
                    f"Выберите подразделение для контрагента «{next_contractor}»:",
                    user_id=user_id,
                    reply_markup=reply_markup
                )
                await session_manager.update_session(task_id, {
                    "status": "waiting_question",
                    "question": {
                        "type": "vz_office_mapping",
                        "contractors": contractors,
                        "offices": offices_options,
                        "current_idx": current_idx
                    }
                })
            else:
                # Все контрагенты обработаны — продолжаем обработку
                await session_manager.update_session(
                    task_id, {"status": "running", "question": None}
                )
                if self.on_cycle_complete:
                    await self.on_cycle_complete(task_id)

    async def show_mappings(self, user_id: int):
        """Показывает пользователю список сохранённых маппингов."""
        mappings = get_all_mappings()
        if not mappings:
            await self.notifier.send_message(
                "Нет сохранённых маппингов.", user_id=user_id
            )
            return
        keyboard = []
        for cont, rep in mappings:
            keyboard.append([{
                "text": f"{cont} → {rep} ❌",
                "callback_data": f"del_mapping|{cont}"
            }])
        keyboard.append([{
            "text": "Отмена",
            "callback_data": "edit_mapping_cancel"
        }])
        reply_markup = {"inline_keyboard": keyboard}
        await self.notifier.send_message(
            "Текущие маппинги. Нажмите для удаления:",
            user_id=user_id,
            reply_markup=reply_markup
        )

    async def show_mapping_stats(self, user_id: int):
        """Показывает статистику сохранённых маппингов."""
        count = get_mapping_count()
        if count == 0:
            await self.notifier.send_message(
                "📭 Нет сохранённых маппингов. Они будут созданы при первой "
                "обработке взаиморасчетов с новыми контрагентами.",
                user_id=user_id
            )
        else:
            await self.notifier.send_message(
                f"💾 Сохранено маппингов: {count}\n"
                f"Они используются при обработке взаиморасчетов — "
                f"контрагенты с известными маппингами пропускаются автоматически.\n\n"
                f"Чтобы посмотреть/удалить маппинги, отправьте /edit_mapping",
                user_id=user_id
            )

    async def delete_mapping(self, task_id: str, contractor: str, session_manager):
        """Удаляет маппинг для контрагента."""
        delete_mapping(contractor)
        state = await session_manager.get_session(task_id)
        if state:
            await self.notifier.send_message(
                f"🗑 Маппинг для «{contractor}» удалён.",
                user_id=state["user_id"]
            )
