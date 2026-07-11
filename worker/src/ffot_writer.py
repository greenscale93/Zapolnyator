"""
Запись/чтение значений в шаблон отчёта по конфигурации из rules.json.

Поддерживает:
- write_values (тип ffot) — расчёт + запись в ячейку (через LibreOffice UNO)
- read_values — чтение значения из ячейки (через calamine)
"""
import logging
import re
import pandas as pd
from typing import Optional, List

from src.template_reader import (
    find_row_by_name, find_month_column, read_cell_at, open_workbook_and_sheet,
    _open_sheet
)
from src.lo_client import lo_client

logger = logging.getLogger(__name__)

MONTHS_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}


def get_month_name(month) -> str:
    """Возвращает название месяца по номеру (1-12) или строке."""
    if isinstance(month, str):
        return month
    return MONTHS_RU.get(month, str(month))


def get_month_number(month_name: str) -> int:
    """Конвертирует название месяца в число."""
    rev_map = {v: k for k, v in MONTHS_RU.items()}
    num = rev_map.get(month_name)
    if num is None:
        raise ValueError(f"Неизвестное название месяца: {month_name}")
    return num


def get_target_month_name(month, offset: int) -> str:
    """Возвращает название месяца со смещением (0 = текущий, -1 = предыдущий)."""
    if isinstance(month, str):
        month_num = get_month_number(month)
    else:
        month_num = month
    target = month_num + offset
    # Циклический сдвиг в пределах года
    while target < 1:
        target += 12
    while target > 12:
        target -= 12
    return MONTHS_RU[target]


def _clean_numeric(value):
    """Очищает значение от неразрывных пробелов и приводит к float."""
    if isinstance(value, str):
        cleaned = re.sub(r'[^\d,.-]', '', value.replace('\u00a0', '').replace(' ', ''))
        cleaned = cleaned.replace(',', '.')
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ===================== WRITE VALUES =====================


async def _write_ffot(
    source_path: str,
    template_path: str,
    config: dict,
    month,
    year: int
) -> dict:
    """
    Обрабатывает write_value типа 'ffot' через LibreOffice UNO.
    """
    # 1. Расчёт суммы
    exclude_emp = config.get("exclude_employee", {})
    ffot_value = _calculate_ffot_sum(source_path, exclude_employee=exclude_emp)

    # 2. Читаем позиции через calamine
    data = _open_sheet(template_path, "Отчетность БИТ 2026")

    target_month = get_target_month_name(month, config.get("month_offset", -1))
    col_idx = find_month_column(data, target_month, config.get("month_row", 2))
    if col_idx is None:
        raise ValueError(f"Не найден месяц '{target_month}'")

    row_num = find_row_by_name(data, config.get("row_column", 3), config.get("row_name", ""))
    if row_num is None:
        raise ValueError(f"Не найдена строка '{config.get('row_name')}'")

    # 3. Запись через LibreOffice
    if lo_client is None:
        raise RuntimeError("LibreOffice UNO not available")

    col_letter = chr(64 + col_idx) if col_idx <= 26 else f"col{col_idx}"
    cell_ref = f"{col_letter}{row_num}"

    doc = await lo_client.open_document(template_path)
    try:
        sheet = await lo_client.get_sheet(doc, "Отчетность БИТ 2026")
        await lo_client.write_cell(sheet, col_idx - 1, row_num - 1, ffot_value)
        await lo_client.save_document(doc, template_path)
        logger.info(f"Записано {config.get('key')}: {ffot_value} в {cell_ref}")
    finally:
        await lo_client.close_document(doc)

    return {"value": ffot_value, "cell": cell_ref, "label": config.get("label", "")}


def _calculate_ffot_sum(
    source_path: str,
    exclude_employee: Optional[dict] = None
) -> float:
    """
    Читает исходный файл, фильтрует ФактическийФОТ,
    суммирует колонку Сумма с исключениями.

    exclude_employee = {"Сорокин Илья Вячеславович": ["Премия"]}
    означает: для указанного сотрудника исключить строки с указанным видом начисления.
    """
    df = pd.read_excel(source_path, header=0, engine='calamine')
    logger.info(f"FFOT: загружено {len(df)} строк, колонки: {list(df.columns)}")

    # Колонка типа записи
    type_col = None
    for col in df.columns:
        if col.lower().strip() in ("типзаписи", "тип записи", "тип", "recordtype"):
            type_col = col
            break
    if not type_col:
        raise ValueError("Не найдена колонка с типом записи (ТипЗаписи)")

    # Фильтр ФактическийФОТ
    df_ffot = df[df[type_col].astype(str).str.strip() == "ФактическийФОТ"]
    if df_ffot.empty:
        logger.warning("Нет строк с ТипЗаписи='ФактическийФОТ'")
        return 0.0

    # Колонки: Сумма, Сотрудник, ВидНачисления
    amount_col = emp_col = payroll_col = None
    for col in df_ffot.columns:
        c = col.lower().strip()
        if amount_col is None and c in ("сумма", "amount"):
            amount_col = col
        if emp_col is None and c in ("сотрудник", "employee", "фио"):
            emp_col = col
        if payroll_col is None and c in ("видначислениязп", "payrolltype"):
            payroll_col = col

    if not amount_col:
        raise ValueError("Не найдена колонка 'Сумма' в исходных данных")

    total = 0.0

    # Суммируем построчно с учётом исключений
    for _, row in df_ffot.iterrows():
        employee = str(row.get(emp_col, "")).strip() if emp_col else ""
        payroll_type = str(row.get(payroll_col, "")).strip() if payroll_col else ""

        # Проверяем исключения: для Сорокина не суммируем Премию
        skip_row = False
        if exclude_employee and employee in exclude_employee:
            excluded_types = exclude_employee[employee]
            if payroll_type in excluded_types:
                logger.info(
                    f"FFOT: исключена строка для {employee} ({payroll_type})"
                )
                skip_row = True

        if not skip_row:
            total += _clean_numeric(row.get(amount_col, 0))

    logger.info(f"FFOT: итог (по колонке Сумма) = {total}")
    return total


# ===================== READ VALUES =====================


def read_value_from_template(
    template_path: str,
    config: dict,
    month,
    year: int
) -> dict:
    """
    Читает значение из шаблона по конфигурации read_value.
    """
    data, _ = open_workbook_and_sheet(template_path)

    target_month = get_target_month_name(month, config.get("month_offset", 0))
    col_idx = find_month_column(data, target_month, config.get("month_row", 2))
    if col_idx is None:
        raise ValueError(
            f"Не найден месяц '{target_month}' в строке {config.get('month_row', 2)}"
        )

    row_num = find_row_by_name(
        data, config.get("row_column", 3), config.get("row_name", "")
    )
    if row_num is None:
        raise ValueError(
            f"Не найдена строка '{config.get('row_name')}' "
            f"в колонке {config.get('row_column', 3)}"
        )

    value = read_cell_at(data, row_num, col_idx)

    col_letter = chr(64 + col_idx) if col_idx <= 26 else f"col{col_idx}"
    cell_ref = f"{col_letter}{row_num}"
    logger.info(f"Прочитано {config.get('key')}: {value} из {cell_ref}")

    return {
        "key": config.get("key"),
        "label": config.get("label", ""),
        "value": value,
        "cell": cell_ref
    }


async def process_write_values(
    source_path: str,
    template_path: str,
    write_values: List[dict],
    month,
    year: int
) -> list:
    """Обрабатывает все write_values из конфига."""
    results = []
    for cfg in write_values:
        try:
            if cfg.get("type") == "ffot":
                result = await _write_ffot(
                    source_path, template_path, cfg, month, year
                )
                results.append(result)
            else:
                logger.warning(f"Неизвестный тип write_value: {cfg.get('type')}")
        except Exception as e:
            logger.exception(f"Ошибка write_value {cfg.get('key')}: {e}")
            results.append({"key": cfg.get("key"), "error": str(e)})
    return results


def process_read_values(
    template_path: str,
    read_values: List[dict],
    month,
    year: int
) -> list:
    """Обрабатывает все read_values из конфига."""
    results = []
    for cfg in read_values:
        try:
            result = read_value_from_template(
                template_path, cfg, month, year
            )
            results.append(result)
        except Exception as e:
            logger.exception(f"Ошибка read_value {cfg.get('key')}: {e}")
            results.append({
                "key": cfg.get("key"),
                "label": cfg.get("label", ""),
                "error": str(e)
            })
    return results
