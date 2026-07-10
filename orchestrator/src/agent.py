import logging
import os
import json
import asyncio
import httpx
import tempfile
import re
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
        self.pending_approval = {}  # task_id -> {prompt_file, history, user_id}
        logger.info("OrchestratorAgent initialized")

    def _load_instruction(self) -> str:
        try:
            with open("/app/INSTRUCTION.md", "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Cannot load instruction: {e}")
            return "Инструкция не загружена."

    async def _send_telegram_message(self, user_id: int, text: str, file_path: str = None):
        """Отправляет сообщение и опционально файл в Telegram с подробным логированием."""
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set")
            return
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Отправляем текстовое сообщение
                msg_resp = await client.post(url, json=payload)
                msg_resp.raise_for_status()
                logger.info(f"Message sent to user {user_id}")

                # Если есть файл — отправляем
                if file_path:
                    if os.path.exists(file_path):
                        file_size = os.path.getsize(file_path)
                        logger.info(f"Sending file: {file_path} ({file_size} bytes)")
                        
                        # Проверяем размер (Telegram limit 50 MB)
                        if file_size > 50 * 1024 * 1024:
                            await client.post(url, json={
                                "chat_id": user_id,
                                "text": f"⚠️ Файл слишком большой ({file_size} байт). Отправка невозможна."
                            })
                            return
                        
                        with open(file_path, 'rb') as f:
                            files = {'document': (os.path.basename(file_path), f, 'text/plain')}
                            doc_resp = await client.post(
                                f"https://api.telegram.org/bot{self.bot_token}/sendDocument",
                                data={'chat_id': user_id},
                                files=files
                            )
                            doc_resp.raise_for_status()
                            logger.info(f"File sent successfully: {file_path}")
                    else:
                        logger.error(f"File not found: {file_path}")
                        await client.post(url, json={
                            "chat_id": user_id,
                            "text": f"❌ Файл не найден: {file_path}"
                        })
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            # Пытаемся отправить сообщение об ошибке
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(url, json={
                        "chat_id": user_id,
                        "text": f"❌ Ошибка отправки: {str(e)[:200]}"
                    })
            except:
                pass

    async def _save_debug_data(self, data, prefix: str) -> str:
        fd, path = tempfile.mkstemp(suffix='.txt', prefix=f"{prefix}_")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            if isinstance(data, (dict, list)):
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            else:
                f.write(str(data))
        logger.info(f"Debug data saved to {path} ({os.path.getsize(path)} bytes)")
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
        mxl_path = files.get("mxl")
        excel_path = files.get("excel")
        if not mxl_path or not excel_path:
            await self._set_error(task_id, "Missing file paths")
            await self._send_telegram_message(user_id, "❌ Ошибка: отсутствуют пути к файлам.")
            return

        month = state.get("month", "Май")
        year = state.get("year", 2026)

        # 1. Конвертируем MXL в CSV
        await self._send_telegram_message(user_id, "🔄 Конвертирую MXL в CSV...")
        convert_result = await self.worker_client.call_tool("convert_mxl_to_csv", {"file_path": mxl_path})
        if convert_result.get("status") == "error":
            await self._set_error(task_id, convert_result.get("error_message"))
            await self._send_telegram_message(user_id, f"❌ Ошибка конвертации MXL: {convert_result.get('error_message')}")
            return
        csv_path = convert_result["result"]["csv_path"]
        csv_data = convert_result["result"]["csv_data"]
        rows = convert_result["result"]["rows"]
        columns = convert_result["result"]["columns"]
        size = convert_result["result"]["size_bytes"]
        
        # Отправляем CSV файл пользователю
        await self._send_telegram_message(
            user_id,
            f"📄 CSV-файл создан ({rows} строк, {size} байт). Отправляю файл.",
            file_path=csv_path
        )

        # 2. Читаем структуру Excel
        await self._send_telegram_message(user_id, "🔍 Читаю структуру Excel...")
        excel_struct = await self.worker_client.call_tool("read_excel_structure", {"file_path": excel_path})
        if excel_struct.get("status") == "error":
            await self._set_error(task_id, excel_struct.get("error_message"))
            await self._send_telegram_message(user_id, f"❌ Ошибка чтения Excel: {excel_struct.get('error_message')}")
            return

        # 3. Формируем системный промпт
        system_prompt = f"""
Ты — ИИ-агент, который заполняет отчёт ДКП по данным из MXL-выгрузки (конвертирована в CSV).
Вот полная инструкция:

{self.instruction}

Файлы уже загружены:
- CSV-данные (все строки) доступны по пути: {csv_path}
- Excel-шаблон: {excel_path}
Месяц: {month}, год: {year}.

Колонки в CSV: {columns}
Всего строк: {rows}

Ты можешь использовать инструменты:
- filter_mxl_data(file_path, filters) — фильтрует CSV-файл по критериям. file_path = {csv_path}. filters — словарь с колонками и значениями. ОДИН ВЫЗОВ может содержать несколько фильтров. 
- write_excel(template_path, sheets_data, password, output_path) — записывает данные в Excel.
- read_excel_structure — уже вызван.

Порядок действий:
1. Определи соответствие колонок (ТипЗаписи, Сценарий, Подразделение, СуммаБезНДС и т.д.). Если неясно — задай вопрос через ask_user.
2. Примени фильтры: Сценарий="ФАКТ", исключи Подразделение="ГКП 10.6 (Емельянова)", исключи ВГО. Для этого сделай ОДИН вызов filter_mxl_data с фильтрами, либо несколько по типам записей.
3. Обработай каждый тип согласно инструкции.
4. Сформируй структуру для записи в Excel (словарь лист->список строк).
5. Вызови write_excel.
6. Вычисли показатели.

Важно: НЕ ДЕЛАЙ МНОГО ВЫЗОВОВ ОДНОГО И ТОГО ЖЕ. Используй filter_mxl_data только для получения данных по типам записей (Реализация, Оплата, Взаиморасчет, НачислениеЗарплаты, ФактическийФОТ).
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
        # Сохраняем состояние ожидания утверждения
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
        await self._send_telegram_message(user_id, "✅ Запрос к LLM одобрен. Начинаю обработку...")
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
                history_str = json.dumps(history, ensure_ascii=False, default=str)
                if len(history_str) > 4000000:
                    debug_file = await self._save_debug_data(history, "history_overflow")
                    await self._send_telegram_message(user_id, f"⚠️ История слишком большая. Сохранена в файл.", file_path=debug_file)
                    history = [history[0]] + history[-3:]
                
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
            pass  # handled by commands

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