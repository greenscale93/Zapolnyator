import logging
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)


def find_column(columns: List[str], keywords: List[str]) -> Optional[str]:
    """Ищет колонку среди columns по ключевым словам."""
    for col in columns:
        col_lower = col.lower().strip()
        for kw in keywords:
            if kw in col_lower:
                return col
    return None


def resolve_columns(
    columns: List[str],
    user_mapping: Optional[Dict[str, str]] = None
) -> dict:
    """
    Определяет соответствие колонок на основе user_mapping или автоопределения.

    Возвращает словарь с найденными колонками и список missing (не найденных обязательных).
    """
    if user_mapping:
        col_type = user_mapping.get("type")
        col_scenario = user_mapping.get("scenario")
        col_department = user_mapping.get("subdivision")
        col_department_contr = user_mapping.get("contractor_department")
        col_report_department = user_mapping.get("report_department")
        col_contractor = user_mapping.get("contractor")
        col_project = user_mapping.get("project")
        col_stage = user_mapping.get("stage")
        col_employee = user_mapping.get("employee")
        col_amount_no_vat = user_mapping.get("amount_no_vat")
        col_amount_with_vat = user_mapping.get("amount_with_vat")
        col_vat_rate = user_mapping.get("vat_rate")
        col_comment = user_mapping.get("comment")
        col_doc_number = user_mapping.get("doc_number")
        col_turnover_type = user_mapping.get("turnover_type")
        col_turnover_view = user_mapping.get("turnover_view")
        col_settlement_type = user_mapping.get("settlement_type")
        col_payroll_type = user_mapping.get("payroll_type")
        col_oklad = user_mapping.get("oklad")
        col_premia = user_mapping.get("premia")
        col_admin_expenses = user_mapping.get("admin_expenses")
        col_amount = user_mapping.get("amount")
        col_direction = user_mapping.get("direction")
        col_vgo = user_mapping.get("vgo")
        col_responsible = user_mapping.get("responsible")
        col_base_doc = user_mapping.get("base_doc")
    else:
        col_type = find_column(columns, ["типзаписи", "тип записи", "тип", "recordtype"])
        col_scenario = find_column(columns, ["сценарий", "scenario"])
        col_department = find_column(columns, ["подразделение", "department", "отдел"])
        col_department_contr = find_column(columns, ["подразделениеконтрагент", "contractordepartment"])
        col_report_department = find_column(columns, ["подразделениеконтрагентдляотчета", "дляотчета", "reportdepartment"])
        col_contractor = find_column(columns, ["контрагент", "contractor", "клиент"])
        col_project = find_column(columns, ["проект", "project"])
        col_stage = find_column(columns, ["этап", "stage"])
        col_employee = find_column(columns, ["сотрудник", "employee", "фио"])
        col_amount_no_vat = find_column(columns, ["суммабезндс", "без ндс", "amountwithoutvat"])
        col_amount_with_vat = find_column(columns, ["суммасндс", "с ндс", "amountwithvat"])
        col_vat_rate = find_column(columns, ["ставкандс", "vatrate", "ндс"])
        col_comment = find_column(columns, ["комментарий", "comment"])
        col_doc_number = find_column(columns, ["номерк7", "документ", "documentnumber"])
        col_turnover_type = find_column(columns, ["типоборота", "turnovertype"])
        col_turnover_view = find_column(columns, ["видоборота", "turnoverview"])
        col_settlement_type = find_column(columns, ["видвзаиморасчета", "settlementtype"])
        col_payroll_type = find_column(columns, ["видначислениязп", "payrolltype"])
        col_oklad = find_column(columns, ["оклад", "salary"])
        col_premia = find_column(columns, ["премия", "bonus"])
        col_admin_expenses = find_column(columns, ["административныерасходы", "administrative"])
        col_amount = find_column(columns, ["сумма", "amount"])
        col_direction = find_column(columns, ["направление", "direction"])
        col_vgo = find_column(columns, ["вго", "vgo"])
        col_responsible = find_column(columns, ["ответственный", "responsible"])
        col_base_doc = find_column(columns, ["документоснование", "basedoc"])

    cols = {
        "type": col_type,
        "scenario": col_scenario,
        "department": col_department,
        "department_contr": col_department_contr,
        "report_department": col_report_department,
        "contractor": col_contractor,
        "project": col_project,
        "stage": col_stage,
        "employee": col_employee,
        "amount_no_vat": col_amount_no_vat,
        "amount_with_vat": col_amount_with_vat,
        "vat_rate": col_vat_rate,
        "comment": col_comment,
        "doc_number": col_doc_number,
        "turnover_type": col_turnover_type,
        "turnover_view": col_turnover_view,
        "settlement_type": col_settlement_type,
        "payroll_type": col_payroll_type,
        "oklad": col_oklad,
        "premia": col_premia,
        "admin_expenses": col_admin_expenses,
        "amount": col_amount,
        "direction": col_direction,
        "vgo": col_vgo,
        "responsible": col_responsible,
        "base_doc": col_base_doc,
    }

    # Определяем обязательные колонки
    missing = []
    if not col_type:
        missing.append("ТипЗаписи")
    if not col_scenario:
        missing.append("Сценарий")
    if not col_department:
        missing.append("Подразделение")

    return {"columns": cols, "missing": missing}
