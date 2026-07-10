import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Константы для фильтрации
EXCLUDED_DEPARTMENT = "ГКП 10.6 (Емельянова)"
VGO_KEYWORDS = ["ВГО", "вго"]
SCENARIO_FAKT = "ФАКТ"
VALID_TYPES = ["Реализация", "Оплата", "Взаиморасчет", "НачислениеЗарплаты", "ФактическийФОТ"]

async def process_data(
    mxl_data: List[Dict[str, str]],
    month: str,
    year: int,
    rules: Dict[str, Any],
    user_mapping: Optional[Dict[str, str]] = None
) -> dict:
    """
    Применяет бизнес-логику к данным из MXL.
    Возвращает данные для каждого листа и фактический ФОТ.
    """
    try:
        if not mxl_data:
            return {"status": "error", "error_message": "No data provided"}

        columns = list(mxl_data[0].keys())
        logger.info(f"Columns detected: {columns}")

        # Определяем колонки (если есть маппинг от пользователя – используем)
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
            col_employee = user_mapping.get("employee")  # дублируется, но оставим
        else:
            # Автоопределение по ключевым словам (для быстрого старта)
            def find_column(keywords: List[str]) -> Optional[str]:
                for col in columns:
                    col_lower = col.lower()
                    for kw in keywords:
                        if kw in col_lower:
                            return col
                return None

            col_type = find_column(["типзаписи", "тип записи"])
            col_scenario = find_column(["сценарий"])
            col_department = find_column(["подразделение"])
            col_department_contr = find_column(["подразделениеконтрагент"])
            col_report_department = find_column(["подразделениеконтрагентдляотчета", "дляотчета"])
            col_contractor = find_column(["контрагент"])
            col_project = find_column(["проект"])
            col_stage = find_column(["этап"])
            col_employee = find_column(["сотрудник"])
            col_amount_no_vat = find_column(["суммабезндс"])
            col_amount_with_vat = find_column(["суммасндс"])
            col_vat_rate = find_column(["ставкандс"])
            col_comment = find_column(["комментарий"])
            col_doc_number = find_column(["номерк7"])
            col_turnover_type = find_column(["типоборота"])
            col_turnover_view = find_column(["видоборота"])
            col_settlement_type = find_column(["видвзаиморасчета"])
            col_payroll_type = find_column(["видначислениязп"])
            col_oklad = find_column(["оклад"])
            col_premia = find_column(["премия"])
            col_admin_expenses = find_column(["административныерасходы"])
            col_amount = find_column(["сумма"])  # для ФОТ фактического
            col_direction = find_column(["направление"])
            col_vgo = find_column(["вго"])
            col_responsible = find_column(["ответственный"])
            col_base_doc = find_column(["документоснование"])

        if not col_type or not col_scenario or not col_department:
            return {
                "status": "needs_clarification",
                "clarification": {
                    "question": "Не удалось определить структуру MXL-файла. Укажите колонки: ТипЗаписи, Сценарий, Подразделение, ПодразделениеКонтрагентДляОтчета (если есть), СуммаБезНДС, СуммаСНДС, СтавкаНДС, Комментарий и др. Ответьте в формате: типзаписи: название, сценарий: название, ...",
                    "context": {
                        "type": "column_mapping",
                        "columns": columns,
                        "missing": [
                            name for name, col in {
                                "типзаписи": col_type,
                                "сценарий": col_scenario,
                                "подразделение": col_department,
                                "подразделениеконтрагентдляотчета": col_report_department,
                                "суммабезндс": col_amount_no_vat,
                                "суммасндс": col_amount_with_vat
                            }.items() if not col
                        ]
                    }
                }
            }

        # 1. Фильтрация: только ФАКТ, исключаем ГКП 10.6, отсекаем ВГО
        filtered_rows = []
        for row in mxl_data:
            scenario = row.get(col_scenario, "").strip()
            department = row.get(col_department, "").strip()
            vgo_value = row.get(col_vgo, "").strip() if col_vgo else ""
            direction = row.get(col_direction, "").strip() if col_direction else ""
            
            # Фильтры
            if scenario != SCENARIO_FAKT:
                continue
            if EXCLUDED_DEPARTMENT in department:
                continue
            if vgo_value.lower() == "да" or any(kw in direction.lower() for kw in VGO_KEYWORDS):
                continue
            
            filtered_rows.append(row)

        if not filtered_rows:
            return {"status": "error", "error_message": "No data after filtering (check filters: ФАКТ, exclude ГКП 10.6, exclude ВГО)"}

        # 2. Группировка по типам записей
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
            # Игнорируем остальные (ИсторияКвалификации, ОкладСотрудника)

        # 3. Обработка ФОТ (НачислениеЗарплаты) – группировка по сотруднику
        payroll_grouped = {}
        for row in payroll_rows:
            if not col_employee or not col_oklad or not col_premia:
                continue
            emp = row.get(col_employee, "").strip()
            if not emp:
                continue
            payroll_type = row.get(col_payroll_type, "").strip() if col_payroll_type else ""
            if payroll_type == "Административные расходы":
                continue  # игнорируем
            if emp not in payroll_grouped:
                payroll_grouped[emp] = {"oklad": 0.0, "premia": 0.0, "comments": [], "department": row.get(col_department, "")}
            if payroll_type == "Оплата труда":
                payroll_grouped[emp]["oklad"] += float(row.get(col_oklad, 0) or 0)
            elif payroll_type == "Премия":
                premia_val = float(row.get(col_premia, 0) or 0)
                payroll_grouped[emp]["premia"] += premia_val
                if row.get(col_comment):
                    payroll_grouped[emp]["comments"].append(row.get(col_comment, ""))
            # Остальные типы игнорируем

        # Преобразуем в список для листа ФОТ
        payroll_list = []
        for emp, data in payroll_grouped.items():
            payroll_list.append({
                "Подразделение": data["department"],
                "Сотрудник": emp,
                "ФОТ": data["oklad"],
                "Премия": data["premia"],
                "Комментарий": "; ".join(data["comments"]) if data["comments"] else ""
            })

        # 4. Обработка взаиморасчетов (Взаиморасчет)
        settlement_processed = []
        # Сначала сгруппируем по документу (НомерК7) для схлопывания
        settlement_groups = {}
        for row in settlement_rows:
            doc_key = row.get(col_doc_number, "").strip()
            if not doc_key:
                continue
            if doc_key not in settlement_groups:
                settlement_groups[doc_key] = []
            settlement_groups[doc_key].append(row)

        for doc_key, rows_group in settlement_groups.items():
            # Определяем, внутренний отдел или другой офис по ПодразделениеКонтрагентДляОтчета
            report_dept = rows_group[0].get(col_report_department, "").strip() if col_report_department else ""
            is_internal = "руб." in report_dept or "Отдел" in report_dept
            is_other_office = "др. офис" in report_dept or not report_dept or any(kw in report_dept.lower() for kw in ["ташкент", "краснодар", "павелецкая", "nfp"])

            if is_internal:
                # Схлопнуть дубль: взять только строку с ТипОборота = БДР (если есть)
                bdr_row = None
                bdds_row = None
                for r in rows_group:
                    to_type = r.get(col_turnover_type, "").strip() if col_turnover_type else ""
                    if to_type == "БДР":
                        bdr_row = r
                    elif to_type == "БДДС":
                        bdds_row = r
                selected = bdr_row if bdr_row else (bdds_row if bdds_row else rows_group[0])
                # Добавляем одну строку
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
                # Разделить по ТипОборота: БДР и БДДС
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
                # Неизвестный тип – добавим как есть (позже потребует уточнения)
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

        # 5. Обработка фактического ФОТ
        fact_ffot_value = 0.0
        for row in fact_ffot_rows:
            employee = row.get(col_employee, "").strip() if col_employee else ""
            payroll_type = row.get(col_payroll_type, "").strip() if col_payroll_type else ""
            amount = float(row.get(col_amount, 0) or 0)
            # Исключаем премию Сорокина Ильи Вячеславовича
            if employee == "Сорокин Илья Вячеславович" and payroll_type == "Премия":
                continue
            fact_ffot_value += amount

        # 6. Подготовка результата
        return {
            "status": "success",
            "result": {
                "realization_rows": realization_rows,  # сырые строки для листа Реализация
                "payment_rows": payment_rows,          # сырые строки для листа ДС
                "payroll_rows": payroll_list,          # сгруппированные данные для ФОТ
                "settlements_rows": settlement_processed,  # обработанные взаиморасчеты
                "fact_ffot_value": fact_ffot_value
            }
        }

    except Exception as e:
        logger.exception("Business logic error")
        return {"status": "error", "error_message": str(e)}