import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

SCENARIO_FAKT = "ФАКТ"


def process_settlements(
    settlement_rows: List[Dict[str, Any]],
    columns: dict,
    month: str,
    year: int
) -> List[Dict[str, Any]]:
    """
    Обрабатывает взаиморасчеты с тремя ветками:
    - is_internal: "руб." или "Отдел" в report_department → берём БДР-строку
    - is_other_office: "др. офис", пустой report_department или города → БДР/БДДС
    - default: все остальные
    """
    col_doc_number = columns.get("doc_number")
    col_report_department = columns.get("report_department")
    col_department = columns.get("department")
    col_contractor = columns.get("contractor")
    col_project = columns.get("project")
    col_direction = columns.get("direction")
    col_amount_no_vat = columns.get("amount_no_vat")
    col_comment = columns.get("comment")
    col_turnover_type = columns.get("turnover_type")
    col_department_contr = columns.get("department_contr")

    settlement_processed = []
    settlement_groups = {}

    for row in settlement_rows:
        doc_key = row.get(col_doc_number, "").strip() if col_doc_number else ""
        if not doc_key:
            continue
        if doc_key not in settlement_groups:
            settlement_groups[doc_key] = []
        settlement_groups[doc_key].append(row)

    for doc_key, rows_group in settlement_groups.items():
        report_dept = rows_group[0].get(col_report_department, "").strip() if col_report_department else ""
        is_internal = "руб." in report_dept or "Отдел" in report_dept
        is_other_office = (
            "др. офис" in report_dept
            or not report_dept
            or any(kw in report_dept.lower() for kw in ["ташкент", "краснодар", "павелецкая", "nfp"])
        )

        if is_internal:
            settlement_processed.extend(
                _process_internal(rows_group, columns, month, year)
            )
        elif is_other_office:
            settlement_processed.extend(
                _process_other_office(rows_group, columns, month, year)
            )
        else:
            settlement_processed.extend(
                _process_default(rows_group, columns, month, year)
            )

    return settlement_processed


def _process_internal(
    rows_group: List[Dict[str, Any]],
    columns: dict,
    month: str,
    year: int
) -> List[Dict[str, Any]]:
    """Внутренние отделы — выбираем БДР-строку."""
    col_turnover_type = columns.get("turnover_type")
    col_department = columns.get("department")
    col_contractor = columns.get("contractor")
    col_project = columns.get("project")
    col_direction = columns.get("direction")
    col_amount_no_vat = columns.get("amount_no_vat")
    col_comment = columns.get("comment")
    col_report_department = columns.get("report_department")

    bdr_row = None
    for r in rows_group:
        to_type = r.get(col_turnover_type, "").strip() if col_turnover_type else ""
        if to_type == "БДР":
            bdr_row = r
            break
    selected = bdr_row if bdr_row else rows_group[0]

    return [{
        "Подразделение": selected.get(col_department, ""),
        "Сценарий": SCENARIO_FAKT,
        "Период": f"{month} {year}",
        "Отдел": selected.get(col_report_department, "Внутренний отдел"),
        "Контрагент": selected.get(col_contractor, ""),
        "Проект": selected.get(col_project, ""),
        "Направление": selected.get(col_direction, ""),
        "Сумма без НДС": float(selected.get(col_amount_no_vat, 0) or 0),
        "Комментарий": selected.get(col_comment, "")
    }]


def _process_other_office(
    rows_group: List[Dict[str, Any]],
    columns: dict,
    month: str,
    year: int
) -> List[Dict[str, Any]]:
    """Другие офисы — разделяем по БДР/БДДС."""
    col_turnover_type = columns.get("turnover_type")
    col_department = columns.get("department")
    col_contractor = columns.get("contractor")
    col_project = columns.get("project")
    col_direction = columns.get("direction")
    col_amount_no_vat = columns.get("amount_no_vat")
    col_comment = columns.get("comment")
    col_department_contr = columns.get("department_contr")

    result = []
    for r in rows_group:
        to_type = r.get(col_turnover_type, "").strip() if col_turnover_type else ""
        if to_type == "БДР":
            dept_name = "Взаиморасчеты с др. офисами по актам"
        elif to_type == "БДДС":
            dept_name = "Взаиморасчеты с др. офисами по ДС"
        else:
            continue
        comment = r.get(col_comment, "")
        office_name = r.get(col_department_contr, "").strip() if col_department_contr else ""
        if office_name and comment:
            comment = f"{office_name}. {comment}"
        elif office_name:
            comment = office_name
        result.append({
            "Подразделение": r.get(col_department, ""),
            "Сценарий": SCENARIO_FAKT,
            "Период": f"{month} {year}",
            "Отдел": dept_name,
            "Контрагент": r.get(col_contractor, ""),
            "Проект": r.get(col_project, ""),
            "Направление": r.get(col_direction, ""),
            "Сумма без НДС": float(r.get(col_amount_no_vat, 0) or 0),
            "Комментарий": comment
        })
    return result


def _process_default(
    rows_group: List[Dict[str, Any]],
    columns: dict,
    month: str,
    year: int
) -> List[Dict[str, Any]]:
    """Обычные офисы — все строки как есть."""
    col_department = columns.get("department")
    col_contractor = columns.get("contractor")
    col_project = columns.get("project")
    col_direction = columns.get("direction")
    col_amount_no_vat = columns.get("amount_no_vat")
    col_comment = columns.get("comment")
    col_report_department = columns.get("report_department")

    result = []
    for r in rows_group:
        result.append({
            "Подразделение": r.get(col_department, ""),
            "Сценарий": SCENARIO_FAKT,
            "Период": f"{month} {year}",
            "Отдел": r.get(col_report_department, "Неизвестный отдел"),
            "Контрагент": r.get(col_contractor, ""),
            "Проект": r.get(col_project, ""),
            "Направление": r.get(col_direction, ""),
            "Сумма без НДС": float(r.get(col_amount_no_vat, 0) or 0),
            "Комментарий": r.get(col_comment, "")
        })
    return result
