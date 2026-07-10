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
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set")
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
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

    async def _save_debug_data(self, data, prefix: str) -> str:
        fd, path = tempfile.mkstemp(suffix='.txt', prefix=f"{prefix}_")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False, default=str))
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
            f"📁 MXL: {mxl_path}\n📁 Excel: {excel_path}"
        )

        # 1. Конвертируем MXL в CSV
        await self._send_telegram_message(user_id, "🔄 Конвертирую MXL в CSV...")
        convert_result = await self.worker_client.call_tool("convert_mxl_to_csv", {"file_path": mxl_path})
        if convert_result.get("status") == "error":
            await self._set_error(task_id, convert_result.get("error_message"))
            await self._send_telegram_message(user_id, f"❌ Ошибка конвертации MXL: {convert_result.get('error_message')}")
            return
        
        csv_data = convert_result["result"]["csv_data"]
        csv_path = convert_result["result"]["csv_path"]
        rows = convert_result["result"]["rows"]
        columns = convert_result["result"]["columns"]

        # Отправляем CSV файл пользователю (всегда)
        await self._send_telegram_message(
            user_id,
            f"📄 CSV-файл создан ({rows} строк, {len(csv_data)} символов).",
            file_path=csv_path
        )

        # Если CSV слишком большой, обрезаем для контекста
        csv_for_context = csv_data
        if len(csv_data) > 200000:  # 200 KB – безопасный лимит
            # Берем первые 500 строк
            lines = csv_data.splitlines()
            header = lines[0] if lines else ""
            body = lines[1:501] if len(lines) > 1 else []
            csv_for_context = header + "\n" + "\n".join(body) + f"\n... (всего {len(lines)} строк, показано 500)"
            await self._send_telegram_message(
                user_id,
                f"⚠️ CSV слишком большой ({len(csv_data)} символов). В контекст отправлено только 500 строк. Полный файл сохранён."
            )

        # 2. Получаем структуру Excel
        await self._send_telegram_message(user_id, "🔍 Читаю структуру Excel...")
        excel_struct = await self.worker_client.call_tool("read_excel_structure", {"file_path": excel_path})
        if excel_struct.get("status") == "error":
            await self._set_error(task_id, excel_struct.get("error_message"))
            await self._send_telegram_message(user_id, f"❌ Ошибка чтения Excel: {excel_struct.get('error_message')}")
            return
        sheets = excel_struct["result"]["sheets"]

        # 3. Формируем системный промпт с полной инструкцией и данными
        system_prompt = f"""
Ты — ИИ-агент, который заполняет отчёт ДКП по данным из MXL-выгрузки.
Вот полная инструкция, которой ты должен следовать:

{self.instruction}

Файлы уже загружены на сервер:
- MXL (конвертирован в CSV): {csv_path}
- Excel-шаблон: {excel_path}
Месяц: {month}, год: {year}.
НЕ ЗАПРАШИВАЙ пути к файлам — они уже известны.

Данные из MXL в формате CSV (первые 500 строк):
{csv_for_context}

Структура Excel:
{json.dumps(sheets, indent=2, ensure_ascii=False)}

Ты можешь использовать инструменты (вызывай через call_tool):
- filter_mxl_data(file_path, filters) — фильтрует данные по критериям (например, {{"Сценарий": "ФАКТ"}}). file_path = {mxl_path}.
- write_excel(template_path, sheets_data, password, output_path) — записывает данные. template_path = {excel_path}.
- read_excel_structure(file_path) — уже вызвано.

Также ты можешь запрашивать уточнения через ask_user.

Порядок действий (строго по инструкции):
1. Определи соответствие колонок: ТипЗаписи, Сценарий, Подразделение, ПодразделениеКонтрагентДляОтчета, СуммаБезНДС, СуммаСНДС, СтавкаНДС, Комментарий, НомерК7, Сотрудник, Оклад, Премия, ВидНачисленияЗП, ТипОборота, ВидОборота, Направление, ВГО.
2. Примени фильтры: Сценарий = "ФАКТ", исключи ГКП 10.6, исключи ВГО.
   Вызывай filter_mxl_data поочерёдно для каждого типа записи:
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "Реализация" }})
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "Оплата" }})
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "Взаиморасчет" }})
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "НачислениеЗарплаты" }})
   - filter_mxl_data(file_path, filters={{ "Сценарий": "ФАКТ", "ТипЗаписи": "ФактическийФОТ" }})
3. Обработай Взаиморасчеты согласно инструкции.
4. Сгруппируй НачислениеЗарплаты по сотруднику.
5. Вычисли фактический ФОТ.
6. Сформируй структуру для записи в Excel:
   - Реализация: Подразделение, Сценарий, Период ("Месяц Год"), Контрагент, Проект, Сумма с НДС, Сумма без НДС, Ставка НДС (преобразовать), Комментарий (Этап), № документа.
   - ДС: аналогично, но Комментарий из колонки Комментарий.
   - ФОТ: Подразделение, Сотрудник, ФОТ, Премия, Комментарий.
   - Взаиморасчеты: Подразделение, Сценарий, Период, Отдел, Контрагент, Проект, Направление (преобразованное), Сумма без НДС, Комментарий.
7. Вызови write_excel.
8. Вычисли итоговые показатели.

Все данные уже на сервере. Используй фильтрацию по типам записей.
"""

        history = [{"role": "system", "content": system_prompt}]
        history.append({"role": "assistant", "content": f"Я проанализирую данные и подготовлю Excel для {month} {year}."})

        max_iterations = 15
        iteration = 0
        total_tokens = 0
        while iteration < max_iterations:
            iteration += 1
            try:
                tools = [{
                    "type": "function",
                    "function": {
                        "name": "call_tool",
                        "description": "Вызвать инструмент Worker",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string", "enum": ["filter_mxl_data", "write_excel", "read_excel_structure", "ask_user"]},
                                "arguments": {"type": "object"}
                            },
                            "required": ["tool", "arguments"]
                        }
                    }
                }]
                
                history_size = len(json.dumps(history, ensure_ascii=False, default=str))
                if history_size > 4000000:
                    debug_file = await self._save_debug_data(history, "history_overflow")
                    await self._send_telegram_message(user_id, f"⚠️ Размер истории ({history_size} символов) превышает лимит. Файл сохранён.", file_path=debug_file)
                    if len(history) > 4:
                        history = [history[0]] + history[-3:]
                    logger.warning(f"History truncated due to size")

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
                logger.info(f"Iteration {iteration}: tokens used = {usage.total_tokens if usage else 'N/A'}, total = {total_tokens}")

                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        args = json.loads(tc.function.arguments)
                        tool_name = args.get("tool")
                        tool_args = args.get("arguments", {})
                        if tool_name == "ask_user":
                            question = tool_args.get("question")
                            context = tool_args.get("context", {})
                            await self._send_telegram_message(user_id, f"❓ Вопрос: {question}")
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
                            await self._send_telegram_message(user_id, f"⚙️ Вызываю {tool_name}...")
                            result = await self.worker_client.call_tool(tool_name, tool_args)
                            if result.get("status") == "error":
                                await self._send_telegram_message(user_id, f"❌ Ошибка {tool_name}: {result.get('error_message')}")
                            else:
                                await self._send_telegram_message(user_id, f"✅ {tool_name} выполнен успешно.")
                            result_str = json.dumps(result, ensure_ascii=False, default=str)
                            if len(result_str) > 3000000:
                                debug_file = await self._save_debug_data(result, f"{tool_name}_result")
                                await self._send_telegram_message(user_id, f"📦 Результат {tool_name} слишком большой ({len(result_str)} символов). Файл сохранён.", file_path=debug_file)
                                if "filtered_data" in result.get("result", {}):
                                    data = result["result"]["filtered_data"]
                                    result["result"]["filtered_data"] = data[:100] if isinstance(data, list) else data
                                    result["result"]["_note"] = f"Показаны первые 100 из {len(data)} строк. Полный файл отправлен."
                                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                            tool_response = {"role": "tool", "tool_call_id": tc.id, "content": result_str}
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
                                    f"✅ Обработка завершена!\n📁 Файл: {output_path}\n📊 Показатели: {metrics}\n🔢 Токенов: {total_tokens}"
                                )
                                logger.info(f"Task {task_id} completed. Total tokens: {total_tokens}")
                                return
                            else:
                                await self._set_error(task_id, result.get("error_message", "Unknown error"))
                                await self._send_telegram_message(user_id, f"❌ Ошибка: {result.get('error_message', 'Неизвестная ошибка')}")
                                return
                        except json.JSONDecodeError:
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
                    await self._send_telegram_message(user_id, f"❌ Ошибка 413: история сохранена в файл.", file_path=debug_file)
                else:
                    await self._send_telegram_message(user_id, f"❌ Критическая ошибка: {error_msg[:200]}")
                await self._set_error(task_id, error_msg)
                return
        await self._set_error(task_id, "Agent reached maximum iterations")
        await self._send_telegram_message(user_id, "❌ Агент достиг лимита итераций.")

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
        await self.session_manager.update_session(task_id, {"status": "error", "error": error_message})