import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

async def process_data(mxl_data: List[Dict[str, str]], month: str, year: int, rules: Dict[str, Any], user_mapping: Optional[Dict[str, str]] = None) -> dict:
    """
    Применяет бизнес-логику к данным из MXL.
    Если user_mapping задан, использует его для определения колонок.
    Возвращает данные для каждого листа и, возможно, запрос на уточнение.
    """
    try:
        if not mxl_data:
            return {"status": "error", "error_message": "No data provided"}
        
        columns = list(mxl_data[0].keys())
        logger.info(f"Columns detected: {columns}")
        
        # Если пользователь уже дал маппинг – используем его
        if user_mapping:
            col_subdivision = user_mapping.get("subdivision")
            col_amount = user_mapping.get("amount")
            col_contractor = user_mapping.get("contractor")
            col_vat = user_mapping.get("vat")
            col_employee = user_mapping.get("employee")
            col_type = user_mapping.get("type")
            logger.info(f"Using user mapping: {user_mapping}")
        else:
            # Автоопределение
            def find_column(keywords: List[str]) -> Optional[str]:
                for col in columns:
                    col_lower = col.lower()
                    for kw in keywords:
                        if kw in col_lower:
                            return col
                return None
            
            col_subdivision = find_column(["подразделение", "отдел", "департамент", "подразд"])
            col_contractor = find_column(["контрагент", "клиент", "заказчик"])
            col_amount = find_column(["сумма", "стоимость", "выручка"])
            col_vat = find_column(["ндс", "ставка ндс"])
            col_employee = find_column(["сотрудник", "фио", "работник"])
            col_type = find_column(["тип", "вид"])
        
        # Если не нашли ключевые колонки – запрашиваем уточнение
        if not col_subdivision or not col_amount:
            return {
                "status": "needs_clarification",
                "clarification": {
                    "question": "Не удалось определить структуру MXL-файла. Укажите, какая колонка соответствует подразделению (например, 'Отдел') и какая – сумме (например, 'Сумма'). Ответьте в формате: подразделение: название_колонки, сумма: название_колонки",
                    "context": {
                        "type": "column_mapping",
                        "columns": columns,
                        "missing": {
                            "subdivision": not col_subdivision,
                            "amount": not col_amount
                        }
                    }
                }
            }
        
        # Группировка данных по листам (упрощённая логика)
        realization_rows = []
        payment_rows = []
        payroll_rows = []
        settlements_rows = []
        fact_ffot_value = 0.0
        
        for row in mxl_data:
            # Определяем тип операции, если есть колонка
            row_type = row.get(col_type, "").lower() if col_type else ""
            amount = float(row.get(col_amount, 0) or 0)
            
            if "реализация" in row_type:
                realization_rows.append(row)
            elif "дс" in row_type or "денежные средства" in row_type:
                payment_rows.append(row)
            elif "фот" in row_type or "зарплата" in row_type:
                payroll_rows.append(row)
                fact_ffot_value += amount
            elif "взаиморасчет" in row_type:
                settlements_rows.append(row)
            else:
                # По умолчанию в реализацию
                realization_rows.append(row)
        
        # Применяем правила из долгосрочной памяти (rules) – пока заглушка
        # Здесь можно добавить маппинг подразделений и исключения
        
        return {
            "status": "success",
            "result": {
                "realization_rows": realization_rows,
                "payment_rows": payment_rows,
                "settlements_rows": settlements_rows,
                "payroll_rows": payroll_rows,
                "fact_ffot_value": fact_ffot_value,
                "detected_mapping": {
                    "subdivision": col_subdivision,
                    "amount": col_amount,
                    "contractor": col_contractor,
                    "vat": col_vat,
                    "employee": col_employee,
                    "type": col_type
                }
            }
        }
    except Exception as e:
        logger.exception("Business logic error")
        return {"status": "error", "error_message": str(e)}