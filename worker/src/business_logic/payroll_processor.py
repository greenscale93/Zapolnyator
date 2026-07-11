import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def process_payroll(
    payroll_rows: List[Dict[str, Any]],
    columns: dict
) -> List[Dict[str, Any]]:
    """
    Группирует зарплатные записи по сотруднику.
    Суммирует Оклад и Премию, собирает комментарии.
    Пропускает 'Административные расходы'.
    Возвращает список словарей для вставки.
    """
    col_employee = columns.get("employee")
    col_oklad = columns.get("oklad")
    col_premia = columns.get("premia")
    col_payroll_type = columns.get("payroll_type")
    col_department = columns.get("department")
    col_comment = columns.get("comment")

    payroll_grouped = {}
    for row in payroll_rows:
        if not col_employee or not col_oklad or not col_premia:
            continue
        emp = row.get(col_employee, "").strip()
        if not emp:
            continue
        payroll_type = row.get(col_payroll_type, "").strip() if col_payroll_type else ""
        if payroll_type == "Административные расходы":
            continue
        if emp not in payroll_grouped:
            payroll_grouped[emp] = {
                "oklad": 0.0,
                "premia": 0.0,
                "comments": [],
                "department": row.get(col_department, "")
            }
        if payroll_type == "Оплата труда":
            payroll_grouped[emp]["oklad"] += float(row.get(col_oklad, 0) or 0)
        elif payroll_type == "Премия":
            premia_val = float(row.get(col_premia, 0) or 0)
            payroll_grouped[emp]["premia"] += premia_val
            if row.get(col_comment):
                payroll_grouped[emp]["comments"].append(row.get(col_comment, ""))

    payroll_list = []
    for emp, data in payroll_grouped.items():
        payroll_list.append({
            "Подразделение": data["department"],
            "Сотрудник": emp,
            "ФОТ": data["oklad"],
            "Премия": data["premia"],
            "Комментарий": "; ".join(data["comments"]) if data["comments"] else ""
        })

    return payroll_list
