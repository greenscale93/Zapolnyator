import logging
from typing import List, Dict, Any, Optional

from .column_mapper import resolve_columns
from .filtering import filter_rows, SCENARIO_FAKT
from .payroll_processor import process_payroll
from .settlement_processor import process_settlements
from .ffot_processor import calculate_ffot

logger = logging.getLogger(__name__)

VALID_TYPES = ["Реализация", "Оплата", "Взаиморасчет", "НачислениеЗарплаты", "ФактическийФОТ"]


async def process_data(
    mxl_data: List[Dict[str, str]],
    month: str,
    year: int,
    rules: Dict[str, Any],
    user_mapping: Optional[Dict[str, str]] = None
) -> dict:
    """
    Оркестрирует обработку данных:
    1. Определение колонок
    2. Фильтрация
    3. Группировка по типам записей
    4. Обработка каждого типа (ЗП, взаиморасчеты, ФОТ)
    """
    try:
        if not mxl_data:
            return {"status": "error", "error_message": "No data provided"}

        columns_list = list(mxl_data[0].keys())
        logger.info(f"Columns detected: {columns_list}")
        logger.info(f"First row sample: {mxl_data[0] if mxl_data else 'empty'}")

        # Шаг 1: Определение колонок
        resolved = resolve_columns(columns_list, user_mapping)
        cols = resolved["columns"]
        missing = resolved["missing"]

        # Логируем выборку
        for i, row in enumerate(mxl_data[:3]):
            logger.info(
                f"Sample row {i}: type={row.get(cols['type'])}, "
                f"scenario={row.get(cols['scenario'])}, "
                f"dept={row.get(cols['department'])}"
            )

        if missing:
            return {
                "status": "needs_clarification",
                "clarification": {
                    "question": (
                        f"Не удалось определить колонки: {', '.join(missing)}. "
                        f"Укажите соответствие колонок. Доступные колонки: {columns_list}"
                    ),
                    "context": {
                        "type": "column_mapping",
                        "columns": columns_list,
                        "missing": missing
                    }
                }
            }

        # Шаг 2: Фильтрация
        filter_result = await filter_rows(mxl_data, cols, month, year)
        if filter_result["status"] == "needs_clarification":
            return filter_result
        filtered_rows = filter_result["filtered_rows"]

        # Шаг 3: Группировка по типам записей
        col_type = cols["type"]
        realization_rows = []
        payment_rows = []
        payroll_rows = []
        settlement_rows = []
        fact_ffot_rows = []

        for row in filtered_rows:
            record_type = row.get(col_type, "").strip()
            if record_type == "Реализация":
                realization_rows.append(row)
            elif record_type == "Оплата":
                payment_rows.append(row)
            elif record_type == "НачислениеЗарплаты":
                payroll_rows.append(row)
            elif record_type == "Взаиморасчет":
                settlement_rows.append(row)
            elif record_type == "ФактическийФОТ":
                fact_ffot_rows.append(row)

        # Шаг 4: Обработка каждого типа
        payroll_list = process_payroll(payroll_rows, cols)
        settlement_processed = process_settlements(settlement_rows, cols, month, year)
        fact_ffot_value = calculate_ffot(fact_ffot_rows, cols)

        return {
            "status": "success",
            "result": {
                "realization_rows": realization_rows,
                "payment_rows": payment_rows,
                "payroll_rows": payroll_list,
                "settlements_rows": settlement_processed,
                "fact_ffot_value": fact_ffot_value
            }
        }

    except Exception as e:
        logger.exception("Business logic error")
        return {"status": "error", "error_message": str(e)}
