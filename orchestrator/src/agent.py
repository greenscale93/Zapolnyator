import logging
import os
import json
import re
from typing import List, Dict, Optional, Any
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

    async def run_agent_cycle(self, task_id: str):
        state = await self.session_manager.get_session(task_id)
        if not state:
            return
        
        rules = await self.memory_store.load_all_rules()
        user_mapping = state.get("user_mapping")
        files = state.get("files", {})
        month = state.get("month", "Май")
        year = state.get("year", 2026)
        
        # 1. parse_mxl
        parse_result = await self.worker_client.call_tool("parse_mxl", {"file_path": files.get("mxl")})
        if parse_result["status"] == "error":
            await self._set_error(task_id, parse_result.get("error_message"))
            return
        mxl_data = parse_result["result"]["data"]
        
        # 2. process_data
        process_args = {
            "mxl_data": mxl_data,
            "month": month,
            "year": year,
            "rules": rules
        }
        if user_mapping:
            process_args["user_mapping"] = user_mapping
        
        process_result = await self.worker_client.call_tool("process_data", process_args)
        if process_result["status"] == "error":
            await self._set_error(task_id, process_result.get("error_message"))
            return
        elif process_result["status"] == "needs_clarification":
            clarification = process_result["clarification"]
            context = clarification["context"]
            # Проверяем, нужно ли предложить маппинг через ИИ
            if context.get("type") == "column_mapping":
                # Добавляем в вопрос список колонок, если ещё не добавлен
                columns = context.get("columns", [])
                sample_data = context.get("sample_data", [])
                # Формируем вопрос с колонками
                question_text = (
                    f"Не удалось определить структуру MXL-файла. Доступные колонки:\n"
                    f"{', '.join(columns)}\n\n"
                    f"Укажите, какая колонка соответствует подразделению и какая – сумме.\n"
                    f"Или просто скажите 'помоги', и я предложу вариант."
                )
                # Сохраняем состояние с вопросом
                await self.session_manager.update_session(task_id, {
                    "status": "waiting_question",
                    "question": {
                        "text": question_text,
                        "context": context
                    },
                    "pending_tool": "process_data",
                    "pending_args": process_args,
                    "mxl_data": mxl_data,  # сохраним для повторных вызовов
                    "attempts": 0  # счётчик попыток
                })
                return
            else:
                # Другие типы вопросов
                await self.session_manager.update_session(task_id, {
                    "status": "waiting_question",
                    "question": {
                        "text": clarification["question"],
                        "context": context
                    },
                    "pending_tool": "process_data",
                    "pending_args": process_args
                })
                return
        
        # Если успешно – продолжаем
        processed_data = process_result["result"]
        # Сохраняем обнаруженный маппинг в память (если он был автоматически определён)
        detected_mapping = processed_data.get("detected_mapping")
        if detected_mapping:
            await self.memory_store.save_column_mapping(detected_mapping)
        
        # 3. update_excel
        excel_result = await self.worker_client.call_tool("update_excel", {
            "template_path": files.get("excel"),
            "data": processed_data,
            "month": month,
            "year": year,
            "password": os.getenv("DEFAULT_PASSWORD", "987456")
        })
        if excel_result["status"] == "error":
            await self._set_error(task_id, excel_result.get("error_message"))
            return
        output_path = excel_result["result"]["output_path"]
        
        # 4. calculate_metrics
        metrics_result = await self.worker_client.call_tool("calculate_metrics", {
            "output_path": output_path,
            "month": month,
            "year": year,
            "payroll_data": processed_data.get("payroll_rows")
        })
        if metrics_result["status"] == "error":
            await self._set_error(task_id, metrics_result.get("error_message"))
            return
        metrics = metrics_result["result"]
        
        # Завершение
        await self.session_manager.update_session(task_id, {
            "status": "done",
            "result_file": output_path,
            "metrics": metrics
        })

    async def process_answer(self, task_id: str, answer: str):
        state = await self.session_manager.get_session(task_id)
        if not state or state.get("status") != "waiting_question":
            return
        
        context = state.get("question", {}).get("context", {})
        pending_args = state.get("pending_args", {})
        mxl_data = state.get("mxl_data")
        attempts = state.get("attempts", 0) + 1
        
        if context.get("type") == "column_mapping":
            # Проверяем, просит ли пользователь помощи
            if "помоги" in answer.lower() or "предлож" in answer.lower() or "какие колонки" in answer.lower():
                # Используем ИИ для предложения маппинга
                suggestion = await self._suggest_mapping_with_ai(context.get("columns", []), context.get("sample_data", []))
                if suggestion:
                    question_text = (
                        f"Я предполагаю, что подразделение — это '{suggestion.get('subdivision')}', "
                        f"а сумма — '{suggestion.get('amount')}'. Подходит?\n"
                        f"Ответьте 'Да' или 'Нет', или укажите свои варианты в формате: "
                        f"подразделение: название, сумма: название"
                    )
                    await self.session_manager.update_session(task_id, {
                        "status": "waiting_question",
                        "question": {
                            "text": question_text,
                            "context": context,
                            "suggestion": suggestion
                        },
                        "pending_args": pending_args,
                        "mxl_data": mxl_data,
                        "attempts": attempts
                    })
                    return
                else:
                    await self._send_message_to_user(task_id, "Не удалось предложить маппинг. Пожалуйста, укажите вручную в формате: подразделение: название, сумма: название")
                    return
            
            # Если пользователь ответил "Да" на предложение
            if "да" in answer.lower() and state.get("question", {}).get("suggestion"):
                mapping = state["question"]["suggestion"]
                await self._apply_mapping_and_continue(task_id, mapping, pending_args)
                return
            
            # Если ответ содержит "Нет"
            if "нет" in answer.lower() and state.get("question", {}).get("suggestion"):
                await self.session_manager.update_session(task_id, {
                    "status": "waiting_question",
                    "question": {
                        "text": "Укажите правильный маппинг в формате: подразделение: название, сумма: название",
                        "context": context
                    },
                    "pending_args": pending_args,
                    "mxl_data": mxl_data,
                    "attempts": attempts
                })
                return
            
            # Попытка распарсить маппинг из ответа
            mapping = self._parse_column_mapping(answer, context.get("columns", []))
            if mapping:
                await self._apply_mapping_and_continue(task_id, mapping, pending_args)
                return
            else:
                # Если не удалось распарсить, и это не первая попытка – используем ИИ
                if attempts > 2:
                    # Передаём весь диалог в ИИ для разбора
                    suggestion = await self._suggest_mapping_with_ai(context.get("columns", []), context.get("sample_data", []), user_answer=answer)
                    if suggestion:
                        question_text = (
                            f"Я понял ваш ответ и предлагаю такой маппинг: подразделение — '{suggestion.get('subdivision')}', "
                            f"сумма — '{suggestion.get('amount')}'. Подходит?"
                        )
                        await self.session_manager.update_session(task_id, {
                            "status": "waiting_question",
                            "question": {
                                "text": question_text,
                                "context": context,
                                "suggestion": suggestion
                            },
                            "pending_args": pending_args,
                            "mxl_data": mxl_data,
                            "attempts": attempts
                        })
                        return
                # Если не удалось, просим заново
                await self.session_manager.update_session(task_id, {
                    "status": "waiting_question",
                    "question": {
                        "text": "Не удалось разобрать ваш ответ. Укажите в формате: подразделение: название_колонки, сумма: название_колонки",
                        "context": context
                    },
                    "pending_args": pending_args,
                    "mxl_data": mxl_data,
                    "attempts": attempts
                })
                return
        else:
            # Другие типы вопросов – пока просто передаём ответ как есть (заглушка)
            await self.session_manager.update_session(task_id, {
                "status": "processing",
                "pending_args": pending_args
            })
            await self.run_agent_cycle(task_id)

    async def _suggest_mapping_with_ai(self, columns: List[str], sample_data: List[Dict], user_answer: str = "") -> Optional[Dict[str, str]]:
        """Использует DeepSeek для предложения маппинга колонок."""
        try:
            prompt = f"""
            Ты — помощник по анализу данных. Даны колонки MXL-файла: {columns}.
            Пример данных (первые строки): {sample_data}.
            {f'Пользователь сказал: {user_answer}. Используй его подсказку, чтобы уточнить маппинг.' if user_answer else ''}
            Определи, какая колонка соответствует "подразделение" и какая "сумма".
            Ответь строго в формате JSON: {{"subdivision": "название_колонки", "amount": "название_колонки"}}.
            Если уверенности нет, выбери наиболее вероятные.
            """
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            content = response.choices[0].message.content
            # Извлекаем JSON из ответа
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                mapping = json.loads(json_match.group())
                if mapping.get("subdivision") and mapping.get("amount"):
                    return mapping
            return None
        except Exception as e:
            logger.error(f"AI suggestion failed: {e}")
            return None

    async def _apply_mapping_and_continue(self, task_id: str, mapping: Dict[str, str], pending_args: dict):
        """Сохраняет маппинг и продолжает обработку."""
        # Сохраняем в память
        await self.memory_store.save_column_mapping(mapping)
        # Обновляем состояние
        await self.session_manager.update_session(task_id, {
            "user_mapping": mapping,
            "pending_args": pending_args,
            "status": "processing"
        })
        # Запускаем цикл заново
        await self.run_agent_cycle(task_id)

    def _parse_column_mapping(self, answer: str, available_columns: List[str]) -> Optional[Dict[str, str]]:
        """Парсит ответ пользователя вида 'подразделение: Отдел, сумма: Сумма'"""
        mapping = {}
        parts = [p.strip() for p in answer.split(',')]
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                # Проверяем, что такая колонка существует (приблизительно)
                if value in available_columns or any(value.lower() in col.lower() for col in available_columns):
                    if 'подраздел' in key or 'отдел' in key:
                        mapping['subdivision'] = value
                    elif 'сум' in key or 'стоим' in key:
                        mapping['amount'] = value
                    elif 'контрагент' in key or 'клиент' in key:
                        mapping['contractor'] = value
                    elif 'ндс' in key:
                        mapping['vat'] = value
                    elif 'сотрудник' in key or 'фио' in key:
                        mapping['employee'] = value
                    elif 'тип' in key or 'вид' in key:
                        mapping['type'] = value
        if mapping.get('subdivision') and mapping.get('amount'):
            return mapping
        return None

    async def _set_error(self, task_id: str, error_message: str):
        await self.session_manager.update_session(task_id, {
            "status": "error",
            "error": error_message
        })

    async def _send_message_to_user(self, task_id: str, message: str):
        # Отправка сообщения пользователю через Gateway
        # В текущей архитектуре мы можем сохранить сообщение в состоянии как вопрос,
        # но это не будет отправлено напрямую. Лучше использовать API Gateway.
        # Пока для простоты мы можем обновить состояние вопроса
        await self.session_manager.update_session(task_id, {
            "status": "waiting_question",
            "question": {"text": message, "context": {}}
        })