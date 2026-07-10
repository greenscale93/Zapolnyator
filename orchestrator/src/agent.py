import logging
import os
import json
import asyncio
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
        logger.info("OrchestratorAgent initialized")

    def _load_instruction(self) -> str:
        try:
            with open("/app/INSTRUCTION.md", "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Cannot load instruction: {e}")
            return "Инструкция не загружена. Пожалуйста, следуйте стандартной бизнес-логике."

    async def run_agent_cycle(self, task_id: str):
        logger.info(f"Starting agent cycle for task {task_id}")
        state = await self.session_manager.get_session(task_id)
        if not state:
            logger.error(f"Task {task_id} not found")
            return
        
        files = state.get("files", {})
        month = state.get("month", "Май")
        year = state.get("year", 2026)
        mxl_path = files.get("mxl")
        excel_path = files.get("excel")
        if not mxl_path or not excel_path:
            await self._set_error(task_id, "Missing file paths")
            return

        # 1. Получаем структуру MXL
        structure_result = await self.worker_client.call_tool("get_mxl_structure", {"file_path": mxl_path})
        if structure_result.get("status") == "error":
            await self._set_error(task_id, structure_result.get("error_message"))
            return
        columns = structure_result["result"]["columns"]
        samples = structure_result["result"]["samples"]
        total_rows = structure_result["result"]["total_rows"]

        # 2. Формируем системный промпт с инструкцией и данными, включая пути к файлам
        system_prompt = f"""
Ты — ИИ-агент, который заполняет отчёт ДКП по данным из MXL-выгрузки.
Вот инструкция, которой ты должен следовать:

{self.instruction}

Сейчас у тебя есть MXL-файл со следующими колонками:
{columns}

Примеры строк (первые 10):
{json.dumps(samples, indent=2, ensure_ascii=False)}

Всего строк: {total_rows}

Пути к файлам (не спрашивай их у пользователя, они уже загружены):
- MXL-файл: {mxl_path}
- Excel-шаблон: {excel_path}

Твоя задача — проанализировать данные и подготовить структуру для записи в Excel.
Ты можешь использовать следующие инструменты (вызывай их через функцию call_tool):
- filter_mxl_data(file_path, filters) — фильтрует данные по критериям (например, {{"Сценарий": "ФАКТ"}}). Используй {mxl_path} как file_path.
- write_excel(template_path, sheets_data, password, output_path) — записывает данные. Используй {excel_path} как template_path.
- read_excel_structure(file_path) — читает структуру Excel (листы и колонки). Используй {excel_path} как file_path.

Также ты можешь запрашивать у пользователя уточнения через функцию ask_user(question, context).

Порядок действий:
1. Определи соответствие колонок: ТипЗаписи, Сценарий, Подразделение, ПодразделениеКонтрагентДляОтчета, СуммаБезНДС, СуммаСНДС, СтавкаНДС, Комментарий, НомерК7, Сотрудник, Оклад, Премия, ВидНачисленияЗП, ТипОборота, ВидОборота, Направление, ВГО.
   Если какая-то колонка не найдена или неоднозначна, задай уточняющий вопрос.
2. Примени фильтры: только Сценарий = "ФАКТ", исключи Подразделение = "ГКП 10.6 (Емельянова)", исключи строки с ВГО = "Да" или Направление содержит "ВГО".
   Для этого вызови filter_mxl_data с соответствующими фильтрами.
3. Сгруппируй данные по типам записей: Реализация, Оплата, Взаиморасчет, НачислениеЗарплаты, ФактическийФОТ.
4. Для Взаиморасчетов обработай согласно инструкции:
   - внутренние отделы (ПодразделениеКонтрагентДляОтчета содержит "руб.") — схлопни дубли (оставь одну строку с ТипОборота="БДР").
   - другие офисы (др. офис, Ташкент, Краснодар, Павелецкая, NFP) — раздели на БДР и БДДС, добавь название офиса в комментарий.
5. Для НачислениеЗарплаты сгруппируй по сотруднику: суммируй Оклад (ВидНачисленияЗП="Оплата труда") и Премию (ВидНачисленияЗП="Премия"), административные расходы игнорируй.
6. Для ФактическийФОТ суммируй Сумму, исключи премию Сорокина Ильи Вячеславовича.
7. Сформируй структуру для записи в Excel: словарь, где ключ — имя листа (Реализация, ДС, ФОТ, Взаиморасчеты), значение — список строк (каждая строка — dict с колонками).
   Колонки для каждого листа определи согласно инструкции.
   Для листа Реализация: Подразделение, Сценарий, Период (текст "Месяц Год"), Контрагент, Проект, Сумма с НДС 20%, Сумма без НДС, Ставка НДС (с преобразованием), Комментарий (Этап), № документа.
   Для листа ДС: аналогично, но Комментарий — из колонки Комментарий.
   Для листа ФОТ: Подразделение, Сотрудник, ФОТ (сумма окладов), Премия (сумма премий), Комментарий (объединённый).
   Для листа Взаиморасчеты: Подразделение, Сценарий, Период, Отдел (результат обработки), Контрагент, Проект, Направление (преобразованное), Сумма без НДС, Комментарий.
8. Вызови write_excel для записи.
9. После записи вычисли итоговые показатели (по формулам из инструкции) и верни их в ответе.

Если на каком-то шаге возникают неопределённости — используй ask_user.
"""

        # 3. Сохраняем историю (системное сообщение + возможные сообщения пользователя)
        history = [{"role": "system", "content": system_prompt}]
        # Добавляем начальное сообщение от ассистента с планом
        init_message = f"Я проанализирую MXL-файл и подготовлю данные для Excel. Месяц: {month}, год: {year}."
        history.append({"role": "assistant", "content": init_message})

        # 4. Цикл вызовов (максимум 10 итераций)
        max_iterations = 10
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            try:
                # Вызов DeepSeek с функцией call_tool
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
                response = await self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=history,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.3,
                )
                msg = response.choices[0].message
                history.append(msg.model_dump())

                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        func_name = tc.function.name
                        args = json.loads(tc.function.arguments)
                        if func_name == "call_tool":
                            tool_name = args.get("tool")
                            tool_args = args.get("arguments", {})
                            if tool_name == "ask_user":
                                # Отправляем вопрос пользователю
                                question = tool_args.get("question")
                                context = tool_args.get("context", {})
                                await self.session_manager.update_session(task_id, {
                                    "status": "waiting_question",
                                    "question": {"text": question, "context": context},
                                    "pending_args": args  # сохраним для возобновления
                                })
                                logger.info(f"Asked user: {question}")
                                return  # выходим из цикла, ждём ответа пользователя
                            else:
                                # Вызываем инструмент Worker
                                result = await self.worker_client.call_tool(tool_name, tool_args)
                                # Добавляем результат в историю
                                tool_response = {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": json.dumps(result, ensure_ascii=False)
                                }
                                history.append(tool_response)
                else:
                    # Ассистент дал финальный ответ
                    content = msg.content
                    if content:
                        # Парсим ответ, ожидаем JSON с результатом
                        try:
                            result = json.loads(content)
                            if result.get("status") == "success":
                                # Завершаем задачу
                                output_path = result.get("output_path")
                                metrics = result.get("metrics", {})
                                await self.session_manager.update_session(task_id, {
                                    "status": "done",
                                    "result_file": output_path,
                                    "metrics": metrics
                                })
                                logger.info(f"Task {task_id} completed successfully")
                                return
                            else:
                                await self._set_error(task_id, result.get("error_message", "Unknown error"))
                                return
                        except json.JSONDecodeError:
                            # Если не JSON, просто считаем это сообщением для пользователя
                            await self.session_manager.update_session(task_id, {
                                "status": "waiting_question",
                                "question": {"text": content, "context": {}}
                            })
                            return
            except Exception as e:
                logger.exception("Agent cycle error")
                await self._set_error(task_id, str(e))
                return
        # Если цикл закончился без результата
        await self._set_error(task_id, "Agent reached maximum iterations without completion")

    async def process_answer(self, task_id: str, answer: str):
        state = await self.session_manager.get_session(task_id)
        if not state or state.get("status") != "waiting_question":
            return
        # Возобновляем цикл с ответом пользователя
        pending_args = state.get("pending_args", {})
        # Добавляем ответ пользователя в историю (сохраняем в сессии)
        history = state.get("history", [])
        if not history:
            history = []
        history.append({"role": "user", "content": answer})
        await self.session_manager.update_session(task_id, {
            "history": history,
            "status": "processing",
            "pending_args": pending_args
        })
        # Продолжаем цикл
        await self.run_agent_cycle(task_id)

    async def _set_error(self, task_id: str, error_message: str):
        logger.error(f"Task {task_id} error: {error_message}")
        await self.session_manager.update_session(task_id, {
            "status": "error",
            "error": error_message
        })