import logging
import os
import json
import asyncio
from src.session_manager import SessionManager
from src.memory import MemoryStore
from src.worker_client import WorkerClient
from src.mapping_store import get_mapping_dict
from src.telegram_notifier import TelegramNotifier
from src.agent.mapping_handler import MappingHandler

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    def __init__(
        self,
        session_manager: SessionManager,
        memory_store: MemoryStore,
        worker_client: WorkerClient
    ):
        self.session_manager = session_manager
        self.memory_store = memory_store
        self.worker_client = worker_client
        self.rules = self._load_rules()

        # Внедряем TelegramNotifier и MappingHandler
        self.notifier = TelegramNotifier()
        self.mapping_handler = MappingHandler(
            notifier=self.notifier,
            on_cycle_complete=self._resume_after_mapping
        )
        logger.info("OrchestratorAgent initialized")

    def _load_rules(self) -> dict:
        try:
            with open("/app/rules.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Cannot load rules: {e}")
            return {}

    async def _resume_after_mapping(self, task_id: str):
        """Callback после завершения маппинга — продолжает цикл агента."""
        asyncio.create_task(self.run_agent_cycle(task_id, resume_from_question=True))

    async def run_agent_cycle(
        self,
        task_id: str,
        resume_from_question: bool = False
    ):
        logger.info(f"Starting agent cycle for task {task_id}")
        state = await self.session_manager.get_session(task_id)
        if not state:
            logger.error(f"Task {task_id} not found")
            return

        user_id = state.get("user_id")
        files = state.get("files", {})
        data_file_path = files.get("data")
        excel_path = files.get("excel")
        if not data_file_path or not excel_path:
            await self._set_error(task_id, "Missing file paths")
            await self.notifier.send_message(
                "❌ Ошибка: отсутствуют пути к файлам.", user_id=user_id
            )
            return

        month = state.get("month", "Май")
        year = state.get("year", 2026)

        sheets_mapping = self.rules.get("sheets", {})
        output_path = state.get("output_path")

        if not resume_from_question:
            for sheet_name, mapping in sheets_mapping.items():
                if sheet_name == "Взаиморасчеты":
                    continue
                await self.notifier.send_message(
                    f"📝 Заполняю лист: {sheet_name}...", user_id=user_id
                )
                result = await self.worker_client.apply_sheet_mapping({
                    "source_path": data_file_path,
                    "template_path": excel_path if output_path is None else output_path,
                    "sheet_name": sheet_name,
                    "mapping": mapping,
                    "month": month,
                    "year": year,
                    "password": "987456",
                    "output_path": output_path
                })
                if result.get("status") == "error":
                    await self._set_error(task_id, result.get("error_message"))
                    await self.notifier.send_message(
                        f"❌ Ошибка: {result.get('error_message')}", user_id=user_id
                    )
                    return
                output_path = result["result"]["output_path"]
                rows_added = result["result"].get("rows_added", "неизвестно")
                await self.notifier.send_message(
                    f"✅ Лист {sheet_name} заполнен (добавлено строк: {rows_added}).",
                    user_id=user_id
                )
                await self.session_manager.update_session(
                    task_id, {"output_path": output_path}
                )

        # Лист "Взаиморасчеты"
        if "Взаиморасчеты" in sheets_mapping:
            vz_mapping = sheets_mapping["Взаиморасчеты"]
            await self.notifier.send_message(
                "📝 Заполняю лист: Взаиморасчеты...", user_id=user_id
            )

            try:
                empty_contractors = await self.worker_client.get_empty_vz_contractors(
                    data_file_path
                )
            except Exception as e:
                logger.exception("Failed to get empty contractors")
                await self._set_error(task_id, str(e))
                await self.notifier.send_message(
                    f"❌ Ошибка получения данных: {str(e)}", user_id=user_id
                )
                return

            saved_mapping = get_mapping_dict()
            unknown = [c for c in empty_contractors if c not in saved_mapping]

            if unknown and not resume_from_question:
                try:
                    offices = await self.worker_client.get_template_offices(excel_path)
                except Exception as e:
                    logger.exception("Failed to get template offices")
                    await self._set_error(
                        task_id, f"Ошибка чтения шаблона: {str(e)}"
                    )
                    await self.notifier.send_message(
                        f"❌ Ошибка чтения шаблона: {str(e)}", user_id=user_id
                    )
                    return

                await self.session_manager.update_session(task_id, {
                    "status": "waiting_question",
                    "question": {
                        "type": "vz_office_mapping",
                        "contractors": unknown,
                        "offices": offices,
                        "current_idx": 0
                    },
                    "offices_options": offices
                })
                contractor = unknown[0]
                reply_markup = {
                    "inline_keyboard": self.mapping_handler.build_office_keyboard(
                        offices, contractor
                    )
                }
                await self.notifier.send_message(
                    f"Выберите подразделение для контрагента «{contractor}»:",
                    user_id=user_id,
                    reply_markup=reply_markup
                )
                return

            vz_mapping_copy = dict(vz_mapping)
            vz_mapping_copy["custom_processing"] = dict(
                vz_mapping["custom_processing"]
            )
            vz_mapping_copy["custom_processing"]["office_mapping"] = saved_mapping

            result = await self.worker_client.apply_sheet_mapping({
                "source_path": data_file_path,
                "template_path": excel_path if output_path is None else output_path,
                "sheet_name": "Взаиморасчеты",
                "mapping": vz_mapping_copy,
                "month": month,
                "year": year,
                "password": "987456",
                "output_path": output_path
            })
            if result.get("status") == "error":
                await self._set_error(task_id, result.get("error_message"))
                await self.notifier.send_message(
                    f"❌ Ошибка: {result.get('error_message')}", user_id=user_id
                )
                return
            output_path = result["result"]["output_path"]
            rows_added = result["result"].get("rows_added", "неизвестно")
            await self.notifier.send_message(
                f"✅ Лист Взаиморасчеты заполнен (добавлено строк: {rows_added}).",
                user_id=user_id
            )
            await self.session_manager.update_session(
                task_id, {"output_path": output_path}
            )

        # ---- Write Values (из rules.json) ----
        write_values = self.rules.get("write_values", [])
        if output_path and write_values:
            try:
                write_results = await self.worker_client.process_write_values(
                    source_path=data_file_path,
                    template_path=output_path,
                    values=write_values,
                    month=month,
                    year=year
                )
                diagnostic = await self.session_manager.get_diagnostic_status(user_id)
                for wr in write_results:
                    if "error" in wr:
                        await self.notifier.send_message(
                            f"⚠️ {wr.get('label', wr.get('key', '?'))}: ошибка {wr['error']}",
                            user_id=user_id
                        )
                    else:
                        val = wr.get('value', 0)
                        val_str = f"{val:,.2f}".replace(",", " ").replace(".", ",")
                        msg = f"📊 {wr.get('label', wr.get('key', '?'))}: {val_str}"
                        if diagnostic:
                            msg += f" ({wr.get('cell', '?')})"
                        await self.notifier.send_message(msg, user_id=user_id)
            except Exception as e:
                logger.warning(f"Write values failed (non-critical): {e}")
                await self.notifier.send_message(
                    f"⚠️ Ошибка записи значений: {str(e)}", user_id=user_id
                )

        # ---- Пересчёт формул в Excel (LibreOffice) ----
        if output_path:
            try:
                await self.worker_client.recalculate_excel(output_path)
                logger.info(f"Formulas recalculated: {output_path}")
            except Exception as e:
                logger.warning(f"Recalculate failed (non-critical): {e}")

        # ---- Read Values (из rules.json) ----
        message_parts = []
        read_values = self.rules.get("read_values", [])
        if output_path and read_values:
            # Проверяем режим диагностики
            diagnostic = await self.session_manager.get_diagnostic_status(user_id)

            try:
                read_results = await self.worker_client.read_template_values(
                    template_path=output_path,
                    values=read_values,
                    month=month,
                    year=year
                )
                for rr in read_results:
                    if "error" in rr:
                        msg = f"⚠️ {rr.get('label', rr.get('key', '?'))}: ошибка"
                    else:
                        val = rr.get("value")
                        cell = rr.get("cell", "?")
                        if val is None:
                            val_str = "пусто"
                        elif isinstance(val, (int, float)):
                            val_str = f"{val:,.2f}".replace(",", " ").replace(".", ",")
                        else:
                            val_str = str(val)

                        # Эмодзи по ключу
                        emoji_map = {
                            "profit_acts": "📈",
                            "profit_money": "💰",
                            "margin_acts": "📊",
                            "margin_money": "💵",
                            "ffot_calculated": "👥",
                            "admin_expenses": "📋",
                            "employees_count": "👤",
                        }
                        emoji = emoji_map.get(rr.get("key", ""), "📊")
                        msg = f"{emoji} {rr.get('label', rr.get('key', '?'))}: {val_str}"
                        if diagnostic:
                            msg += f" ({cell})"
                    message_parts.append(msg)
                if message_parts:
                    await self.notifier.send_message(
                        "\n".join(message_parts), user_id=user_id
                    )
                    if diagnostic:
                        logger.info(f"Diagnostic read_values: {message_parts}")
            except Exception as e:
                logger.warning(f"Read values failed (non-critical): {e}")

        if output_path:
            await self.session_manager.update_session(task_id, {
                "status": "done",
                "result_file": output_path,
                "metrics": {}
            })
        else:
            await self._set_error(task_id, "No output file generated")

    async def handle_answer(self, task_id: str, answer_data: str):
        await self.mapping_handler.process_answer(
            answer_data, self.session_manager, task_id
        )

    async def edit_mapping_command(self, user_id: int):
        await self.mapping_handler.show_mappings(user_id)

    async def handle_delete_mapping(self, task_id: str, contractor: str):
        await self.mapping_handler.delete_mapping(
            task_id, contractor, self.session_manager
        )

    async def stop_task(self, task_id: str):
        await self.session_manager.update_session(task_id, {
            "status": "cancelled",
            "error": "Остановлено пользователем"
        })
        logger.info(f"Task {task_id} stopped by user")

    async def _set_error(self, task_id: str, error_message: str):
        logger.error(f"Task {task_id} error: {error_message}")
        await self.session_manager.update_session(task_id, {
            "status": "error",
            "error": error_message
        })
