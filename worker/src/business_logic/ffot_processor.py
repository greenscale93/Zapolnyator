import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def calculate_ffot(
    fact_ffot_rows: List[Dict[str, Any]],
    columns: dict
) -> float:
    """
    Рассчитывает Фактический ФОТ.
    Суммирует все amount, исключая Премию Сорокина Ильи Вячеславовича.
    """
    col_employee = columns.get("employee")
    col_payroll_type = columns.get("payroll_type")
    col_amount = columns.get("amount")

    fact_ffot_value = 0.0
    for row in fact_ffot_rows:
        employee = row.get(col_employee, "").strip() if col_employee else ""
        payroll_type = row.get(col_payroll_type, "").strip() if col_payroll_type else ""
        amount = float(row.get(col_amount, 0) or 0)
        if employee == "Сорокин Илья Вячеславович" and payroll_type == "Премия":
            continue
        fact_ffot_value += amount

    return fact_ffot_value
