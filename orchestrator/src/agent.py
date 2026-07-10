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
            f"📁 MXL: {mxl_path}\n"
            f"📁 Excel: {excel_path}"
        )

        # 1. Конвертируем MXL в CSV
        await self._send_telegram_message(user_id, "🔍 Конвертирую MXL в CSV...")
        convert_result = await self.worker_client.call_tool("convert_mxl_to_csv", {"file_path": mxl_path})
        if convert_result.get("status") == "error":
            await self._set_error(task_id, convert_result.get("error_message"))
            await self._send_telegram_message(user_id, f"❌ Ошибка конвертации MXL: {convert_result.get('error_message')}")
            return
        csv_path = convert_result["result"]["csv_path"]
        csv_data = convert_result["result"]["csv_data"]
        rows = convert_result["result"]["rows"]
        columns = convert_result["result"]["columns"]
        size = convert_result["result"]["size"]
        await self._send_telegram_message(
            user_id,
            f"✅ MXL сконвертирован в CSV: {rows} строк, размер {size} байт.\n"
            f"📁 CSV сохранён: {csv_path}"
        )

        # Если CSV большой, отправляем пользователю и передаём в LLM только первые строки
        csv_for_llm = csv_data
        if size > 500000:  # 500 KB
            # Сохраняем полный CSV в файл и отправляем пользователю
            debug_file = await self._save_debug_data({"csv_data": csv_data}, "full_csv")
            await self._send_telegram_message(
                user_id,
                f"📦 CSV файл большой ({size} байт). Полный файл сохранён и отправлен.",
                file_path=debug_file
            )
            # Оставляем только первые 200 строк для LLM
            lines = csv_data.splitlines()
            if len(lines) > 200:
                csv_for_llm = "\n".join(lines[:200]) + f"\n... (всего {len(lines)} строк, полный файл отправлен пользователю)"
            else:
                csv_for_llm = csv_data

        # 2. Формируем системный промпт с инструкцией и CSV-данными
        system_prompt = f"""
Ты — ИИ-агент, который заполняет отчёт ДКП по данным из MXL-выгрузки (сконвертированной в CSV).
Вот полная инструкция, которой ты должен следовать:

{self.instruction}

ВАЖНО: файлы уже загружены на сервер и доступны по следующим путям:
- MXL-файл (оригинал): {mxl_path}
- CSV-файл (сконвертированный): {csv_path}
- Excel-шаблон: {excel_path}
Месяц: {month}, год: {year}.

Содержимое CSV-файла (первые строки):
{csv_for_llm}

Всего строк в CSV: {rows}, колонки: {columns}.

Ты можешь использовать следующие инструменты (вызывай их через функцию call_tool):
- filter_mxl_data(file_path, filters) — фильтрует данные из MXL-файла (оригинал). file_path = {mxl_path}. 
  Используй этот инструмент, если тебе нужны полные данные для конкретного типа записей.
- write_excel(template_path, sheets_data, password, output_path) — записывает данные в Excel. template_path = {excel_path}.
- read_excel_structure(file_path) — читает структуру Excel.

Также ты можешь запрашивать у пользователя уточнения через функцию ask_user(question, context), если не хватает информации.

Порядок действий:
1. Проанализируй CSV-данные (уже в промпте) и определи соответствие колонок.
2. Если нужно полные данные для каких-то типов, используй filter_mxl_data с фильтрами.
3. Примени бизнес-логику согласно инструкции:
   - Фильтры: только ФАКТ, исключить ГКП 10.6, исключить ВГО.
   - Группировка по типам записей.
   - Обработка взаиморасчетов (схлопывание, разделение по БДР/БДДС).
   - Группировка ФОТ по сотрудникам.
   - Расчёт фактического ФОТ.
4. Сформируй структуру для записи в Excel.
5. Вызови write_excel.
6. Вычисли итоговые показатели и верни их в JSON-ответе.

Не запрашивай пути к файлам, они уже известны. Используй предоставленные данные.
"""

        # 3. Сохраняем историю
        history = [{"role": "system", "content": system_prompt}]
        init_message = f"Я проанализирую CSV-данные и подготовлю Excel. Месяц: {month}, год: {year}."
        history.append({"role": "assistant", "content": init_message})

        # 4. Цикл вызовов
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
                # Проверка размера истории перед отправкой
                history_size = len(json.dumps(history, ensure_ascii=False, default=str))
                if history_size > 4000000:
                    debug_file = await self._save_debug_data(history, "history_overflow")
                    await self._send_telegram_message(
                        user_id,
                        f"⚠️ Размер истории ({history_size} символов) превышает лимит. Сохранено в файл.",
                        file_path=debug_file
                    )
                    if len(history) > 4:
                        history = [history[0]] + history[-3:]
                    logger.warning(f"History truncated to 4 messages due to size")

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
                                if len(result_str) > 3000000:
                                    debug_file = await self._save_debug_data(result, f"{tool_name}_result")
                                    await self._send_telegram_message(
                                        user_id,
                                        f"📦 Результат {tool_name} слишком большой ({len(result_str)} символов). Сохранён в файл.",
                                        file_path=debug_file
                                    )
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