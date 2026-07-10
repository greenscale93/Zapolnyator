import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

async def process_data(mxl_data: List[Dict[str, str]], month: str, year: int, rules: Dict[str, Any]) -> dict:
    """
    Применяет бизнес-логику к данным из MXL.
    Возвращает данные для каждого листа и, возможно, запрос на уточнение.
    """
    try:
        # 1. Определяем структуру колонок (поиск по ключевым словам)
        columns = list(mxl_data[0].keys()) if mxl_data else []
        logger.info(f"Columns detected: {columns}")
        
        # 2. Ищем колонки по ключевым словам (регистронезависимо)
        def find_column(keywords: List[str]) -> Optional[str]:
            for col in columns:
                col_lower = col.lower()
                for kw in keywords:
                    if kw in col_lower:
                        return col
            return None
        
        # Основные колонки (пример, можно расширить)
        col_subdivision = find_column(["подразделение", "отдел", "департамент", "подразд"])
        col_contractor = find_column(["контрагент", "клиент", "заказчик"])
        col_amount = find_column(["сумма", "стоимость", "выручка"])
        col_vat = find_column(["ндс", "ставка ндс"])
        col_employee = find_column(["сотрудник", "фио", "работник"])
        col_type = find_column(["тип", "вид"])
        
        if not col_subdivision or not col_amount:
            return {
                "status": "needs_clarification",
                "clarification": {
                    "question": "Не удалось определить структуру MXL-файла. Укажите, какие колонки соответствуют подразделению и сумме.",
                    "context": {"columns": columns}
                }
            }
        
        # 3. Группируем данные по листам (условно, по типу операции)
        # Здесь мы используем упрощённую логику: все строки идут в Реализацию, ДС, ФОТ, Взаиморасчеты
        # На практике нужно анализировать типы операций, но для примера разобьём по наличию колонок
        
        realization_rows = []
        payment_rows = []
        payroll_rows = []
        settlements_rows = []
        
        fact_ffot_value = 0.0
        
        for row in mxl_data:
            # Пример: если есть колонка "тип", можно классифицировать
            row_type = row.get(col_type, "").lower() if col_type else ""
            amount = float(row.get(col_amount, 0) or 0)
            
            # Логика классификации (заглушка, нужно доработать под реальные данные)
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
                # Если тип не определён, направляем в реализацию
                realization_rows.append(row)
        
        # 4. Применяем правила из долгосрочной памяти (rules)
        # rules содержит загруженные правила из SQLite
        # Здесь можно добавить обработку: маппинг подразделений, исключения и т.д.
        
        return {
            "status": "success",
            "result": {
                "realization_rows": realization_rows,
                "payment_rows": payment_rows,
                "payroll_rows": payroll_rows,
                "settlements_rows": settlements_rows,
                "fact_ffot_value": fact_ffot_value
            }
        }
    except Exception as e:
        logger.exception("Business logic error")
        return {"status": "error", "error_message": str(e)}