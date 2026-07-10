import logging
import os
import json
import asyncio
import httpx
import tempfile
from openai import AsyncOpenAI
from src.session_manager import SessionManager
from src.memory import MemoryStore
from src.worker_client import WorkerClient

logger = logging.getLogger(__name__)

class OrchestratorAgent:
    def __init__(self, session_manager: SessionManager, memory_store: MemoryStore, worker_client: WorkerClient):
        self.session_manager = session_manager
        self.memory_store = memory_store
        self.worker_client = worker_client
        self.client = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/v1"
        )
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.instruction = self._load_instruction()
        logger.info("OrchestratorAgent initialized")

    def _load_instruction(self) -> str:
        try:
            with open("/app/INSTRUCTION.md", "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Cannot load instruction: {e}")
            return "Инструкция не загружена."

    async def _send_telegram_message(self, user_id: int, text: str, file_path: str = None):
        """Отправляет сообщение пользователю через Telegram API, опционально с файлом."""
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set, cannot send notification")
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": user_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=payload)
            if file_path and os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    files = {'document': (os.path.basename(file_path), f, 'text/plain')}
                    await client.post(
                        f"https://api.telegram.org/bot{self.bot_token}/sendDocument",
                        data={'chat_id': user_id},
                        files=files
                    )
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    async def _save_debug_data(self, data: dict, prefix: str) -> str:
        fd, path = tempfile.mkstemp(suffix='.txt', prefix=f"{prefix}_")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
        return path

    async def run_agent_cycle(self, task_id: str):
        logger.info(f"Starting agent cycle for task {task_id}")
        state = await self.session_manager.get_session(task_id)
        if not state:
            logger.error(f"Task {task_id} not found")
            return
        
        user_id = state.get("user_id")
        files = state.get("files", {})
        mxl_path = files.get("mxl")
        excel_path = files.get("excel")
        if not mxl_path or not excel_path:
            await self._set_error(task_id, "Missing file paths")
            await self._send_telegram_message(user_id, "❌ Ошибка: отсутствуют пути к файлам.")
            return

        month = state.get("month", "Май")
        year = state.get("year", 2026)

        await self._send_telegram_message(
            user_id,
            f"🔄 Начинаю обработку файлов для {month} {year}.\n"
            f"📁 MXL: {mxl_path}\n"
            f"📁 Excel: {excel_path}"
        )

        # 1. Получаем структуру MXL
        await self._send_telegram_message(user_id, "🔍 Анализирую структуру MXL-файла...")
        structure_result = await self.worker_client.call_tool("get_mxl_structure", {"file_path": mxl_path})
        if structure_result.get("status") == "error":
            await self._set_error(task_id, structure_result.get("error_message"))
            await self._send_telegram_message(user_id, f"❌ Ошибка при получении структуры MXL: {structure_result.get('error_message')}")
            return
        columns = structure_result["result"]["columns"]
        samples = structure_result["result"]["samples"]
        total_rows = structure_result["result"]["total_rows"]
        await self._send_telegram_message(
            user_id,
            f"✅ Обнаружено {total_rows} строк, колонки: {', '.join(columns[:10])}{'...' if len(columns) > 10 else ''}"
        )

        # 2. Формируем системный промпт с полной инструкцией
        system_prompt = f"""
Ты — ИИ-агент, который заполняет отчёт ДКП по данным из MXL-выгрузки.
Вот полная инструкция, которой ты должен следовать:

{self.instruction}

ВАЖНО: файлы уже загружены на сервер и доступны по следующим путям:
- MXL-файл: {mxl_path}
- Excel-шаблон: {excel_path}
Месяц: {month}, год: {year}.
НЕ ЗАПРАШИВАЙ пути к файлам — они уже известны.

Сейчас у тебя есть MXL-файл со следующими колонками:
{columns}

Общее количество строк: {total_rows}. 

Ты можешь использовать следующие инструменты (вызывай их через функцию call_tool):
- get_mxl_structure — уже вызван, структура у тебя есть.
- filter_mxl_data(file_path, filters) — фильтрует данные по критериям (например, {{"Сценарий": "ФАКТ"}}). file_path = {mxl_path}. Если результат слишком большой (более 3 МБ), ты получишь урезанный ответ и файл будет отправлен пользователю.
- write_excel(template_path, sheets_data, password, output_path) — записывает данные. template_path = {excel_path}.
- read_excel_structure(file_path) — читает структуру Excel.

Также ты можешь запрашивать у пользователя уточнения через функцию ask_user(question, context), но только если действительно не хватает информации.

Порядок действий (строго следуй инструкции):
1. Определи соответствие колонок: ТипЗаписи, Сценарий, Подразделение, ПодразделениеКонтрагентДляОтчета, СуммаБезНДС, СуммаСНДС, СтавкаНДС, Комментарий, НомерК7, Сотрудник, Оклад, Премия, ВидНачисленияЗП, ТипОборота, ВидОборота, Направление, ВГО.
2. Примени фильтры: только Сценарий = "ФАКТ", исключи Подразделение = "ГКП 10.6 (Емельянова)", исключи ВГО.
   Для этого вызывай filter_mxl_data поочерёдно для каждого типа записи:
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "Реализация" }})
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "Оплата" }})
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "Взаиморасчет" }})
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "НачислениеЗарплаты" }})
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "ФактическийФОТ" }})
   Так каждый ответ будет содержать только строки одного типа.
3. Для Взаиморасчетов обработай согласно инструкции:
   - внутренние отделы (ПодразделениеКонтрагентДляОтчета содержит "руб.") — схлопни дубли (оставь одну строку с ТипОборота="БДР").
   - другие офисы (др. офис, Ташкент, Краснодар, Павелецкая, NFP) — раздели на БДР и БДДС, добавь название офиса в комментарий.
4. Для НачислениеЗарплаты сгруппируй по сотруднику: суммируй Оклад (ВидНачисленияЗП="Оплата труда") и Премию (ВидНачисленияЗП="Премия"), административные расходы игнорируй.
5. Для ФактическийФОТ суммируй Сумму, исключи премию Сорокина Ильи Вячеславовича.
6. Сформируй структуру для записи в Excel: словарь, где ключ — имя листа (Реализация, ДС, ФОТ, Взаиморасчеты), значение — список строк (каждая строка — dict с колонками).
   Колонки для каждого листа определи согласно инструкции.
   Для листа Реализация: Подразделение, Сценарий, Период (текст "Месяц Год"), Контрагент, Проект, Сумма с НДС 20%, Сумма без НДС, Ставка НДС (с преобразованием), Комментарий (Этап), № документа.
   Для листа ДС: аналогично, но Комментарий — из колонки Комментарий.
   Для листа ФОТ: Подразделение, Сотрудник, ФОТ (сумма окладов), Премия (сумма премий), Комментарий (объединённый).
   Для листа Взаиморасчеты: Подразделение, Сценарий, Период, Отдел (результат обработки), Контрагент, Проект, Направление (преобразованное), Сумма без НДС, Комментарий.
8. Вызови write_excel для записи.
9. После записи вычисли итоговые показатели (по формулам из инструкции) и верни их в ответе.

Все данные уже на сервере, не запрашивай пути. Используй пошаговую фильтрацию по типам записей.
"""

        # 3. Сохраняем историю
        history = [{"role": "system", "content": system_prompt}]
        init_message = f"Я проанализирую MXL-файл и подготовлю данные для Excel. Месяц: {month}, год: {year}."
        history.append({"role": "assistant", "content": init_message})

        # 4. Цикл вызовов (максимум 15 итераций)
        max_iterations = 15
        iteration = 0
        total_tokens = 0
        while iteration < max_iterations:
            iteration += 1
            try:
                tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": "call_tool",
                            "description": "Вызвать инструмент Worker",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "tool": {
                                        "type": "string",
                                        "enum": ["filter_mxl_data", "write_excel", "read_excel_structure", "ask_user"]
                                    },
                                    "arguments": {
                                        "type": "object",
                                        "description": "Аргументы для инструмента"
                                    }
                                },
                                "required": ["tool", "arguments"]
                            }
                        }
                    }
                ]
                # Проверяем размер истории перед отправкой
                history_size = len(json.dumps(history, ensure_ascii=False))
                if history_size > 4000000:  # ~4 MB
                    debug_file = await self._save_debug_data(history, "history_overflow")
                    await self._send_telegram_message(
                        user_id,
                        f"⚠️ Размер истории ({history_size} символов) превышает лимит. Сохранено в файл.",
                        file_path=debug_file
                    )
                    # Обрезаем историю
                    if len(history) > 4:
                        history = [history[0]] + history[-3:]
                    logger.warning(f"History truncated from {len(history)} to 4 messages due to size")

                response = await self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=history,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.3,
                )
                msg = response.choices[0].message
                usage = response.usage
                total_tokens += usage.total_tokens if usage else 0
                history.append(msg.model_dump())

                logger.info(f"Iteration {iteration}: tokens used = {usage.total_tokens if usage else 'N/A'}, total so far = {total_tokens}")

                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        func_name = tc.function.name
                        args = json.loads(tc.function.arguments)
                        if func_name == "call_tool":
                            tool_name = args.get("tool")
                            tool_args = args.get("arguments", {})
                            if tool_name == "ask_user":
                                question = tool_args.get("question")
                                context = tool_args.get("context", {})
                                await self._send_telegram_message(user_id, f"❓ Вопрос к пользователю: {question}")
                                await self.session_manager.update_session(task_id, {
                                    "status": "waiting_question",
                                    "question": {"text": question, "context": context},
                                    "pending_args": args,
                                    "history": history,
                                    "total_tokens": total_tokens
                                })
                                logger.info(f"Asked user: {question}")
                                return
                            else:
                                await self._send_telegram_message(user_id, f"⚙️ Вызываю инструмент: {tool_name}...")
                                result = await self.worker_client.call_tool(tool_name, tool_args)
                                if result.get("status") == "error":
                                    await self._send_telegram_message(user_id, f"❌ Ошибка при вызове {tool_name}: {result.get('error_message')}")
                                else:
                                    await self._send_telegram_message(user_id, f"✅ Инструмент {tool_name} выполнен успешно.")
                                # Проверяем размер результата
                                result_str = json.dumps(result, ensure_ascii=False, default=str)
                                if len(result_str) > 3000000:  # 3 MB
                                    # Сохраняем в файл и отправляем пользователю
                                    debug_file = await self._save_debug_data(result, f"{tool_name}_result")
                                    await self._send_telegram_message(
                                        user_id,
                                        f"📦 Результат {tool_name} слишком большой ({len(result_str)} символов). Сохранён в файл.",
                                        file_path=debug_file
                                    )
                                    # Сокращаем результат для LLM
                                    if "filtered_data" in result.get("result", {}):
                                        data = result["result"]["filtered_data"]
                                        truncated = data[:100] if isinstance(data, list) else data
                                        result["result"]["filtered_data"] = truncated
                                        result["result"]["_note"] = f"Показаны только первые 100 из {len(data)} строк. Полный файл отправлен пользователю."
                                        result_str = json.dumps(result, ensure_ascii=False, default=str)
                                tool_response = {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": result_str
                                }
                                history.append(tool_response)
                else:
                    content = msg.content
                    if content:
                        try:
                            result = json.loads(content)
                            if result.get("status") == "success":
                                output_path = result.get("output_path")
                                metrics = result.get("metrics", {})
                                await self.session_manager.update_session(task_id, {
                                    "status": "done",
                                    "result_file": output_path,
                                    "metrics": metrics,
                                    "total_tokens": total_tokens
                                })
                                await self._send_telegram_message(
                                    user_id,
                                    f"✅ Обработка завершена успешно!\n"
                                    f"📁 Файл: {output_path}\n"
                                    f"📊 Показатели: {metrics}\n"
                                    f"🔢 Всего токенов использовано: {total_tokens}"
                                )
                                logger.info(f"Task {task_id} completed successfully. Total tokens: {total_tokens}")
                                return
                            else:
                                await self._set_error(task_id, result.get("error_message", "Unknown error"))
                                await self._send_telegram_message(user_id, f"❌ Ошибка: {result.get('error_message', 'Неизвестная ошибка')}")
                                return
                        except json.JSONDecodeError:
                            # Если не JSON, считаем это сообщением для пользователя
                            await self._send_telegram_message(user_id, f"🤖 {content[:500]}...")
                            await self.session_manager.update_session(task_id, {
                                "status": "waiting_question",
                                "question": {"text": content, "context": {}},
                                "history": history,
                                "total_tokens": total_tokens
                            })
                            return
            except Exception as e:
                logger.exception("Agent cycle error")
                error_msg = str(e)
                if "413" in error_msg or "Request Entity Too Large" in error_msg:
                    debug_file = await self._save_debug_data(history, "413_error_history")
                    await self._send_telegram_message(
                        user_id,
                        f"❌ Ошибка 413: запрос слишком большой. История сохранена в файл.",
                        file_path=debug_file
                    )
                else:
                    await self._send_telegram_message(user_id, f"❌ Критическая ошибка: {error_msg[:200]}")
                await self._set_error(task_id, error_msg)
                return
        await self._set_error(task_id, "Agent reached maximum iterations without completion")
        await self._send_telegram_message(user_id, "❌ Агент достиг максимального числа итераций без завершения.")

    async def process_answer(self, task_id: str, answer: str):
        state = await self.session_manager.get_session(task_id)
        if not state or state.get("status") != "waiting_question":
            return
        user_id = state.get("user_id")
        pending_args = state.get("pending_args", {})
        history = state.get("history", [])
        history.append({"role": "user", "content": answer})
        total_tokens = state.get("total_tokens", 0)
        await self.session_manager.update_session(task_id, {
            "history": history,
            "status": "processing",
            "pending_args": pending_args,
            "total_tokens": total_tokens
        })
        await self._send_telegram_message(user_id, f"📥 Ответ получен: {answer[:100]}...")
        await self.run_agent_cycle(task_id)

    async def _set_error(self, task_id: str, error_message: str):
        logger.error(f"Task {task_id} error: {error_message}")
        await self.session_manager.update_session(task_id, {
            "status": "error",
            "error": error_message
        })