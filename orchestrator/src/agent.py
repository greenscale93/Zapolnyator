import logging
import os
import json
import asyncio
import httpx
import tempfile
import re
import csv
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
        self.pending_approval = {}
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
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(url, json=payload)
                if file_path and os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    if file_size > 50 * 1024 * 1024:
                        await client.post(url, json={
                            "chat_id": user_id,
                            "text": f"⚠️ Файл слишком большой ({file_size} байт). Отправка невозможна."
                        })
                        return
                    with open(file_path, 'rb') as f:
                        files = {'document': (os.path.basename(file_path), f, 'text/plain')}
                        await client.post(
                            f"https://api.telegram.org/bot{self.bot_token}/sendDocument",
                            data={'chat_id': user_id},
                            files=files
                        )
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    async def _save_debug_data(self, data, prefix: str) -> str:
        fd, path = tempfile.mkstemp(suffix='.txt', prefix=f"{prefix}_")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            if isinstance(data, (dict, list)):
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            else:
                f.write(str(data))
        return path

    def _sanitize_for_json(self, obj):
        if isinstance(obj, str):
            return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', obj)
        elif isinstance(obj, dict):
            return {self._sanitize_for_json(k): self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_json(item) for item in obj]
        else:
            return obj

    async def run_agent_cycle(self, task_id: str):
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
            await self._send_telegram_message(user_id, "❌ Ошибка: отсутствуют пути к файлам.")
            return

        month = state.get("month", "Май")
        year = state.get("year", 2026)

        # 1. Читаем данные и создаём CSV для фильтрации
        if data_file_path.lower().endswith(('.xlsx', '.xls')):
            await self._send_telegram_message(user_id, "📊 Читаю данные из Excel...")
            read_result = await self.worker_client.call_tool("read_excel_data", {"file_path": data_file_path})
            if read_result.get("status") == "error":
                await self._set_error(task_id, read_result.get("error_message"))
                await self._send_telegram_message(user_id, f"❌ Ошибка чтения Excel: {read_result.get('error_message')}")
                return
            data = read_result["result"]["data"]
            columns = read_result["result"]["columns"]
            total_rows = read_result["result"]["rows"]
            # Сохраняем в CSV для filter_mxl_data
            csv_path = data_file_path + ".temp.csv"
            with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                writer.writerows(data)
            data_path_for_tool = csv_path
            data_source = "Excel (преобразован в CSV)"
            await self._send_telegram_message(user_id, f"📄 Excel прочитан ({total_rows} строк), сохранён как CSV для фильтрации.")
        else:
            # MXL — конвертируем в CSV
            await self._send_telegram_message(user_id, "🔄 Конвертирую MXL в CSV...")
            convert_result = await self.worker_client.call_tool("convert_mxl_to_csv", {"file_path": data_file_path})
            if convert_result.get("status") == "error":
                await self._set_error(task_id, convert_result.get("error_message"))
                await self._send_telegram_message(user_id, f"❌ Ошибка конвертации MXL: {convert_result.get('error_message')}")
                return
            csv_path = convert_result["result"]["csv_path"]
            columns = convert_result["result"]["columns"]
            total_rows = convert_result["result"]["rows"]
            data_source = "MXL (преобразован в CSV)"
            data_path_for_tool = csv_path
            await self._send_telegram_message(
                user_id,
                f"📄 CSV-файл создан ({total_rows} строк). Отправляю файл.",
                file_path=csv_path
            )

        # 2. Читаем структуру Excel (только один раз)
        await self._send_telegram_message(user_id, "🔍 Читаю структуру Excel...")
        excel_struct = await self.worker_client.call_tool("read_excel_structure", {"file_path": excel_path})
        if excel_struct.get("status") == "error":
            await self._set_error(task_id, excel_struct.get("error_message"))
            await self._send_telegram_message(user_id, f"❌ Ошибка чтения Excel: {excel_struct.get('error_message')}")
            return

        # 3. Формируем системный промпт с чёткими инструкциями
        system_prompt = f"""
Ты — ИИ-агент, который заполняет отчёт ДКП по данным из выгрузки.
Источник данных: {data_source}.
Колонки: {columns}
Всего строк: {total_rows}
Данные доступны по пути (используй его для filter_mxl_data): {data_path_for_tool}
Excel-шаблон: {excel_path}
Месяц: {month}, год: {year}.

Инструкция:
{self.instruction}

Ты можешь использовать инструменты:
- filter_mxl_data(file_path, filters) — фильтрует данные по колонкам. file_path = {data_path_for_tool}. filters — словарь с колонками и значениями.
- write_excel(template_path, sheets_data, password, output_path) — записывает данные в Excel.

ВАЖНО: 
1. НЕ вызывай read_excel_structure — он уже вызван. Структура Excel у тебя есть, используй её.
2. Если filter_mxl_data возвращает 0 строк для какого-то типа — значит, таких записей нет, просто пропусти этот тип.
3. Для каждого типа записи (Реализация, Оплата, Взаиморасчет, НачислениеЗарплаты, ФактическийФОТ) делай ОДИН вызов filter_mxl_data с фильтром по ТипЗаписи.
4. После получения данных обработай их согласно инструкции и сформируй sheets_data для write_excel.
5. Верни JSON с ключами "status": "success", "output_path": "/path/to/result.xlsx", "metrics": {{...}}.

Порядок действий:
1. Вызови filter_mxl_data с {{"ТипЗаписи": "Реализация", "Сценарий": "ФАКТ"}} — получи данные.
2. Вызови filter_mxl_data с {{"ТипЗаписи": "Оплата", "Сценарий": "ФАКТ"}}.
3. Вызови filter_mxl_data с {{"ТипЗаписи": "Взаиморасчет", "Сценарий": "ФАКТ"}}.
4. Вызови filter_mxl_data с {{"ТипЗаписи": "НачислениеЗарплаты", "Сценарий": "ФАКТ"}}.
5. Вызови filter_mxl_data с {{"ТипЗаписи": "ФактическийФОТ", "Сценарий": "ФАКТ"}}.
6. Обработай каждый тип согласно инструкции (группировки, преобразования).
7. Сформируй sheets_data (словарь с ключами: "Реализация", "ДС", "ФОТ", "Взаиморасчеты").
8. Вызови write_excel с template_path={excel_path}, sheets_data=..., password="987456".
9. Верни результат.

Не делай лишних вызовов. Если данные отсутствуют, просто пропускай шаг.
"""

        # Сохраняем промпт в файл для утверждения
        prompt_file = await self._save_debug_data(
            {"system_prompt": system_prompt, "user_id": user_id, "task_id": task_id},
            "llm_prompt"
        )
        await self._send_telegram_message(
            user_id,
            f"📝 Сформирован запрос к LLM. Для продолжения отправьте /approve, для отмены /cancel. Файл с промптом:",
            file_path=prompt_file
        )
        await self.session_manager.update_session(task_id, {
            "status": "waiting_llm_approval",
            "pending_prompt_file": prompt_file,
            "pending_system_prompt": system_prompt,
            "pending_history": [{"role": "system", "content": system_prompt}]
        })
        self.pending_approval[task_id] = {
            "user_id": user_id,
            "prompt_file": prompt_file,
            "history": [{"role": "system", "content": system_prompt}]
        }
        logger.info(f"Task {task_id} waiting for approval")

    async def approve_llm_request(self, task_id: str):
        if task_id not in self.pending_approval:
            return
        pending = self.pending_approval.pop(task_id)
        user_id = pending["user_id"]
        history = pending["history"]
        await self._send_telegram_message(user_id, "✅ Запрос к LLM одобрен. Начинаю обработку... Это может занять некоторое время, пожалуйста, ожидайте.")
        await self._run_llm_cycle(task_id, history, user_id)

    async def cancel_llm_request(self, task_id: str):
        if task_id in self.pending_approval:
            pending = self.pending_approval.pop(task_id)
            user_id = pending["user_id"]
            await self._send_telegram_message(user_id, "❌ Запрос к LLM отменён.")
            await self.session_manager.update_session(task_id, {
                "status": "cancelled",
                "error": "Отменено пользователем"
            })

    async def _run_llm_cycle(self, task_id: str, history: list, user_id: int):
        max_iterations = 10
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
                                        "enum": ["filter_mxl_data", "write_excel", "ask_user"]
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
                # Проверка размера истории
                history_str = json.dumps(history, ensure_ascii=False, default=str)
                if len(history_str) > 4000000:
                    debug_file = await self._save_debug_data(history, "history_overflow")
                    await self._send_telegram_message(user_id, f"⚠️ История слишком большая. Сохранена в файл.", file_path=debug_file)
                    history = [history[0]] + history[-3:]
                
                await self._send_telegram_message(user_id, f"⏳ Отправляю запрос в DeepSeek (итерация {iteration})...")
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
                logger.info(f"Iteration {iteration}: tokens used = {usage.total_tokens}, total = {total_tokens}")

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
                                await self._send_telegram_message(user_id, f"❓ Вопрос: {question}")
                                await self.session_manager.update_session(task_id, {
                                    "status": "waiting_question",
                                    "question": {"text": question, "context": context},
                                    "history": history,
                                    "total_tokens": total_tokens
                                })
                                return
                            else:
                                if tool_name == "filter_mxl_data" and "filters" in tool_args:
                                    filters = tool_args["filters"]
                                    await self._send_telegram_message(user_id, f"⚙️ filter_mxl_data с фильтрами: {filters}")
                                else:
                                    await self._send_telegram_message(user_id, f"⚙️ Вызов {tool_name}")
                                result = await self.worker_client.call_tool(tool_name, tool_args)
                                if result.get("status") == "error":
                                    await self._send_telegram_message(user_id, f"❌ Ошибка {tool_name}: {result.get('error_message')}")
                                else:
                                    await self._send_telegram_message(user_id, f"✅ {tool_name} выполнен успешно.")
                                result = self._sanitize_for_json(result)
                                result_str = json.dumps(result, ensure_ascii=False, default=str)
                                if len(result_str) > 3000000:
                                    debug_file = await self._save_debug_data(result, f"{tool_name}_result")
                                    await self._send_telegram_message(user_id, f"📦 Результат {tool_name} большой ({len(result_str)} символов). Сохранён в файл.", file_path=debug_file)
                                    if "filtered_data" in result.get("result", {}):
                                        data = result["result"]["filtered_data"]
                                        truncated = data[:100] if isinstance(data, list) else data
                                        result["result"]["filtered_data"] = truncated
                                        result["result"]["_note"] = f"Показаны первые 100 из {len(data)} строк. Полный файл отправлен."
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
                                    f"✅ Обработка завершена!\n📁 Файл: {output_path}\n📊 Показатели: {metrics}\n🔢 Токенов: {total_tokens}"
                                )
                                return
                            else:
                                await self._set_error(task_id, result.get("error_message", "Unknown error"))
                                await self._send_telegram_message(user_id, f"❌ Ошибка: {result.get('error_message')}")
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
                logger.exception("LLM cycle error")
                await self._send_telegram_message(user_id, f"❌ Критическая ошибка: {str(e)[:200]}")
                await self._set_error(task_id, str(e))
                return
        await self._set_error(task_id, "Max iterations reached")
        await self._send_telegram_message(user_id, "❌ Достигнуто максимальное число итераций.")

    async def process_answer(self, task_id: str, answer: str):
        state = await self.session_manager.get_session(task_id)
        if not state:
            return
        status = state.get("status")
        if status == "waiting_question":
            user_id = state.get("user_id")
            history = state.get("history", [])
            history.append({"role": "user", "content": answer})
            total_tokens = state.get("total_tokens", 0)
            await self.session_manager.update_session(task_id, {
                "history": history,
                "status": "processing",
                "total_tokens": total_tokens
            })
            await self._send_telegram_message(user_id, f"📥 Ответ получен: {answer[:100]}...")
            await self._run_llm_cycle(task_id, history, user_id)
        elif status == "waiting_llm_approval":
            pass

    async def stop_task(self, task_id: str):
        if task_id in self.pending_approval:
            await self.cancel_llm_request(task_id)
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
        
    async def _load_rules(self) -> dict:
        try:
            with open("/app/rules.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Cannot load rules: {e}")
            return {}