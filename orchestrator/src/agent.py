import logging
import os
import json
import asyncio
import httpx
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
        self.instruction = self._load_instruction()
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        logger.info("OrchestratorAgent initialized")

    def _load_instruction(self) -> str:
        try:
            with open("/app/INSTRUCTION.md", "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Cannot load instruction: {e}")
            return "Инструкция не загружена. Пожалуйста, следуйте стандартной бизнес-логике."

    async def _send_notification(self, user_id: int, text: str):
        """Отправляет уведомление пользователю через Telegram Bot API."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={"chat_id": user_id, "text": text})
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

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
            await self._set_error(task_id, "Missing file paths", user_id)
            return

        month = state.get("month", "Май")
        year = state.get("year", 2026)

        # Уведомление: начало
        await self._send_notification(user_id, "🚀 Начинаю обработку...")

        # 1. Получаем структуру MXL
        await self._send_notification(user_id, "📊 Анализирую структуру MXL...")
        structure_result = await self.worker_client.call_tool("get_mxl_structure", {"file_path": mxl_path})
        if structure_result.get("status") == "error":
            await self._set_error(task_id, structure_result.get("error_message"), user_id)
            return
        columns = structure_result["result"]["columns"]
        samples = structure_result["result"]["samples"][:3]  # только 3 образца
        total_rows = structure_result["result"]["total_rows"]
        await self._send_notification(user_id, f"📊 Найдено колонок: {len(columns)}, строк: {total_rows}")

        # 2. Формируем системный промпт (сокращённый)
        system_prompt = f"""
Ты — ИИ-агент для заполнения отчёта ДКП.
ИНСТРУКЦИЯ (кратко):
{self.instruction[:1500]}  # обрезаем до 1500 символов

Данные:
- MXL: {mxl_path}
- Excel: {excel_path}
- Месяц: {month}, год: {year}
Колонки: {columns}
Примеры (3 строки): {json.dumps(samples, indent=2, ensure_ascii=False)}

Используй инструменты: filter_mxl_data, write_excel, read_excel_structure, ask_user.
Не запрашивай пути к файлам.
Применяй фильтры: Сценарий="ФАКТ", исключи "ГКП 10.6", исключи ВГО.
Группируй по типам записей.
Для Взаиморасчетов: внутренние отделы (с "руб.") – схлопни по БДР; другие офисы – раздели на БДР/БДДС, добавь офис в комментарий.
Для ФОТ: группируй по сотруднику, суммируй Оклад и Премию.
Для ФактическийФОТ: суммируй, исключи премию Сорокина.
Сформируй sheets_data для write_excel.
Верни JSON с полями: status ("success" или "error"), output_path, metrics (если success), или error_message.
Ответ должен быть только JSON.
"""

        # 3. История (системный промпт + начальное сообщение)
        history = [{"role": "system", "content": system_prompt}]
        history.append({"role": "assistant", "content": f"Начинаю обработку. Месяц: {month}, год: {year}."})

        # 4. Цикл вызовов (максимум 5 итераций для экономии)
        max_iterations = 5
        iteration = 0
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
                # Ограничиваем историю последними 10 сообщениями (чтобы не перегружать)
                history_limited = history[-10:] if len(history) > 10 else history
                response = await self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=history_limited,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=1000,
                )
                msg = response.choices[0].message
                # Добавляем ответ в историю (но не всю, а только это сообщение)
                history.append(msg.model_dump())

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
                                # Отправляем вопрос пользователю
                                await self._send_notification(user_id, f"❓ {question}")
                                await self.session_manager.update_session(task_id, {
                                    "status": "waiting_question",
                                    "question": {"text": question, "context": context},
                                    "pending_args": args,
                                    "history": history  # сохраняем историю для продолжения
                                })
                                logger.info(f"Asked user: {question}")
                                return
                            else:
                                # Вызываем инструмент Worker
                                result = await self.worker_client.call_tool(tool_name, tool_args)
                                # Уведомление о результате
                                if tool_name == "filter_mxl_data":
                                    count = result.get("result", {}).get("count", 0)
                                    await self._send_notification(user_id, f"🔍 Применил фильтры: осталось {count} строк.")
                                elif tool_name == "write_excel":
                                    output_path = result.get("result", {}).get("output_path")
                                    if output_path:
                                        await self._send_notification(user_id, f"✅ Excel сохранён: {output_path}")
                                tool_response = {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": json.dumps(result, ensure_ascii=False)
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
                                await self._send_notification(user_id, f"✅ Обработка завершена! Файл: {output_path}")
                                if metrics:
                                    await self._send_notification(user_id, f"📊 Показатели: {json.dumps(metrics, ensure_ascii=False)}")
                                await self.session_manager.update_session(task_id, {
                                    "status": "done",
                                    "result_file": output_path,
                                    "metrics": metrics
                                })
                                logger.info(f"Task {task_id} completed successfully")
                                return
                            else:
                                await self._set_error(task_id, result.get("error_message", "Unknown error"), user_id)
                                return
                        except json.JSONDecodeError:
                            # Если не JSON, считаем это сообщением для пользователя
                            await self._send_notification(user_id, f"ℹ️ {content}")
                            await self.session_manager.update_session(task_id, {
                                "status": "waiting_question",
                                "question": {"text": content, "context": {}}
                            })
                            return
            except Exception as e:
                logger.exception("Agent cycle error")
                await self._set_error(task_id, str(e), user_id)
                return
        await self._set_error(task_id, "Agent reached maximum iterations without completion", user_id)

    async def process_answer(self, task_id: str, answer: str):
        state = await self.session_manager.get_session(task_id)
        if not state or state.get("status") != "waiting_question":
            return
        user_id = state.get("user_id")
        pending_args = state.get("pending_args", {})
        history = state.get("history", [])
        # Добавляем ответ пользователя в историю
        history.append({"role": "user", "content": answer})
        await self._send_notification(user_id, f"✅ Ответ принят: {answer}")
        await self.session_manager.update_session(task_id, {
            "history": history,
            "status": "processing",
            "pending_args": pending_args
        })
        await self.run_agent_cycle(task_id)

    async def _set_error(self, task_id: str, error_message: str, user_id: int = None):
        logger.error(f"Task {task_id} error: {error_message}")
        if user_id:
            await self._send_notification(user_id, f"❌ Ошибка: {error_message}")
        await self.session_manager.update_session(task_id, {
            "status": "error",
            "error": error_message
        })