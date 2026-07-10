import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

EXCLUDED_DEPARTMENT = "ГКП 10.6 (Емельянова)"
VGO_KEYWORDS = ["ВГО", "вго", "внутригрупповые"]
SCENARIO_FAKT = "ФАКТ"
VALID_TYPES = ["Реализация", "Оплата", "Взаиморасчет", "НачислениеЗарплаты", "ФактическийФОТ"]

async def process_data(
    mxl_data: List[Dict[str, str]],
    month: str,
    year: int,
    rules: Dict[str, Any],
    user_mapping: Optional[Dict[str, str]] = None
) -> dict:
    try:
        if not mxl_data:
            return {"status": "error", "error_message": "No data provided"}

        columns = list(mxl_data[0].keys())
        logger.info(f"Columns detected: {columns}")
        logger.info(f"First row sample: {mxl_data[0] if mxl_data else 'empty'}")

        def find_column(keywords: List[str]) -> Optional[str]:
            for col in columns:
                col_lower = col.lower().strip()
                for kw in keywords:
                    if kw in col_lower:
                        return col
            return None

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
            col_type = find_column(["типзаписи", "тип записи", "тип", "recordtype"])
            col_scenario = find_column(["сценарий", "scenario"])
            col_department = find_column(["подразделение", "department", "отдел"])
            col_department_contr = find_column(["подразделениеконтрагент", "contractordepartment"])
            col_report_department = find_column(["подразделениеконтрагентдляотчета", "дляотчета", "reportdepartment"])
            col_contractor = find_column(["контрагент", "contractor", "клиент"])
            col_project = find_column(["проект", "project"])
            col_stage = find_column(["этап", "stage"])
            col_employee = find_column(["сотрудник", "employee", "фио"])
            col_amount_no_vat = find_column(["суммабезндс", "без ндс", "amountwithoutvat"])
            col_amount_with_vat = find_column(["суммасндс", "с ндс", "amountwithvat"])
            col_vat_rate = find_column(["ставкандс", "vatrate", "ндс"])
            col_comment = find_column(["комментарий", "comment"])
            col_doc_number = find_column(["номерк7", "документ", "documentnumber"])
            col_turnover_type = find_column(["типоборота", "turnovertype"])
            col_turnover_view = find_column(["видоборота", "turnoverview"])
            col_settlement_type = find_column(["видвзаиморасчета", "settlementtype"])
            col_payroll_type = find_column(["видначислениязп", "payrolltype"])
            col_oklad = find_column(["оклад", "salary"])
            col_premia = find_column(["премия", "bonus"])
            col_admin_expenses = find_column(["административныерасходы", "administrative"])
            col_amount = find_column(["сумма", "amount"])
            col_direction = find_column(["направление", "direction"])
            col_vgo = find_column(["вго", "vgo"])
            col_responsible = find_column(["ответственный", "responsible"])
            col_base_doc = find_column(["документоснование", "basedoc"])

        missing = []
        if not col_type:
            missing.append("ТипЗаписи")
        if not col_scenario:
            missing.append("Сценарий")
        if not col_department:
            missing.append("Подразделение")
        if missing:
            return {
                "status": "needs_clarification",
                "clarification": {
                    "question": f"Не удалось определить колонки: {', '.join(missing)}. Укажите соответствие колонок. Доступные колонки: {columns}",
                    "context": {
                        "type": "column_mapping",
                        "columns": columns,
                        "missing": missing
                    }
                }
            }

        # Логируем выборку
        for i, row in enumerate(mxl_data[:3]):
            logger.info(f"Sample row {i}: type={row.get(col_type)}, scenario={row.get(col_scenario)}, dept={row.get(col_department)}")

        # Фильтрация
        filtered_rows = []
        for row in mxl_data:
            scenario = row.get(col_scenario, "").strip()
            department = row.get(col_department, "").strip()
            vgo_value = row.get(col_vgo, "").strip() if col_vgo else ""
            direction = row.get(col_direction, "").strip() if col_direction else ""

            if scenario.upper() != SCENARIO_FAKT:
                continue
            if EXCLUDED_DEPARTMENT in department:
                continue
            if vgo_value.lower() == "да" or any(kw in direction.lower() for kw in VGO_KEYWORDS):
                continue
            filtered_rows.append(row)

        if not filtered_rows:
            sample_rows = mxl_data[:5] if mxl_data else []
            sample_info = []
            for row in sample_rows:
                sample_info.append({
                    "type": row.get(col_type, ""),
                    "scenario": row.get(col_scenario, ""),
                    "department": row.get(col_department, "")
                })
            return {
                "status": "needs_clarification",
                "clarification": {
                    "question": f"После фильтрации не осталось данных. Проверьте, что в выгрузке есть записи со сценарием '{SCENARIO_FAKT}' и они не относятся к '{EXCLUDED_DEPARTMENT}'. Образцы: {sample_info}",
                    "context": {
                        "type": "filtering_issue",
                        "sample_rows": sample_info,
                        "columns": columns
                    }
                }
            }

        # Далее группировка по типам записей (как раньше)
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

        # Обработка ФОТ (группировка по сотруднику)
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
                payroll_grouped[emp] = {"oklad": 0.0, "premia": 0.0, "comments": [], "department": row.get(col_department, "")}
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

        # Обработка взаиморасчетов
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
            is_other_office = "др. офис" in report_dept or not report_dept or any(kw in report_dept.lower() for kw in ["ташкент", "краснодар", "павелецкая", "nfp"])

            if is_internal:
                bdr_row = None
                for r in rows_group:
                    to_type = r.get(col_turnover_type, "").strip() if col_turnover_type else ""
                    if to_type == "БДР":
                        bdr_row = r
                        break
                selected = bdr_row if bdr_row else rows_group[0]
                settlement_processed.append({
                    "Подразделение": selected.get(col_department, ""),
                    "Сценарий": SCENARIO_FAKT,
                    "Период": f"{month} {year}",
                    "Отдел": report_dept or "Внутренний отдел",
                    "Контрагент": selected.get(col_contractor, ""),
                    "Проект": selected.get(col_project, ""),
                    "Направление": selected.get(col_direction, ""),
                    "Сумма без НДС": float(selected.get(col_amount_no_vat, 0) or 0),
                    "Комментарий": selected.get(col_comment, "")
                })
            elif is_other_office:
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
                    settlement_processed.append({
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
            else:
                for r in rows_group:
                    settlement_processed.append({
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

        # Фактический ФОТ
        fact_ffot_value = 0.0
        for row in fact_ffot_rows:
            employee = row.get(col_employee, "").strip() if col_employee else ""
            payroll_type = row.get(col_payroll_type, "").strip() if col_payroll_type else ""
            amount = float(row.get(col_amount, 0) or 0)
            if employee == "Сорокин Илья Вячеславович" and payroll_type == "Премия":
                continue
            fact_ffot_value += amount

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