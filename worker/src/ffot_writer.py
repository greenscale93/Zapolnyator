"""
Запись значения ФактическийФОТ в шаблон отчёта.

Содержит:
- find_row_by_name — поиск строки по тексту в колонке
- find_month_column — поиск колонки месяца в шапке
- calculate_ffot_sum — расчёт суммы из выгрузки
- write_ffot_to_template — запись в шаблон
"""
import logging
import re
import pandas as pd
import openpyxl
from openpyxl.utils import get_column_letter
from typing import Optional

logger = logging.getLogger(__name__)

MONTHS_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}


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


def find_row_by_name(ws, column: int, name: str) -> Optional[int]:
    """
    Находит номер строки, в которой в указанной колонке (1-based)
    содержится искомый текст.

    Args:
        ws: Лист openpyxl.
        column: Номер колонки (1 = A, 3 = C, etc.).
        name: Текст для поиска.

    Returns:
        Номер строки или None, если не найдено.
    """
    for row in range(1, ws.max_row + 1):
        cell_value = ws.cell(row=row, column=column).value
        if cell_value and name.strip() in str(cell_value).strip():
            logger.info(f"Найдена строка '{name}' в {get_column_letter(column)}{row}")
            return row
    logger.warning(f"Строка '{name}' не найдена в колонке {get_column_letter(column)}")
    return None


def find_month_column(ws, month_name: str, search_row: int = 2) -> Optional[int]:
    """
    Находит номер колонки, в которой в указанной строке шапки
    содержится название месяца.

    Args:
        ws: Лист openpyxl.
        month_name: Название месяца (например, "Май").
        search_row: Строка шапки с месяцами (по умолчанию 2).

    Returns:
        Номер колонки (1-based) или None.
    """
    for col in range(1, ws.max_column + 1):
        cell_value = ws.cell(row=search_row, column=col).value
        if cell_value and month_name.strip() in str(cell_value).strip():
            logger.info(f"Найден месяц '{month_name}' в {get_column_letter(col)}{search_row}")
            return col
    logger.warning(f"Месяц '{month_name}' не найден в строке {search_row}")
    return None


def get_previous_month_name(month) -> str:
    """Возвращает название месяца, предшествующего указанному.

    month может быть числом (1-12) или строкой-названием ("Июнь").
    """
    if isinstance(month, str):
        # Конвертируем название месяца в число
        rev_map = {v: k for k, v in MONTHS_RU.items()}
        month_num = rev_map.get(month)
        if month_num is None:
            raise ValueError(f"Неизвестное название месяца: {month}")
    else:
        month_num = month
    prev = month_num - 1
    if prev == 0:
        prev = 12
    return MONTHS_RU[prev]


def calculate_ffot_sum(source_path: str, columns_config: Optional[dict] = None) -> float:
    """
    Читает исходный файл выгрузки, фильтрует строки с ТипЗаписи="ФактическийФОТ"
    и суммирует значения из колонок Оклад и Премия.

    Args:
        source_path: Путь к файлу выгрузки (Excel).
        columns_config: Опциональный маппинг колонок (как в user_mapping).

    Returns:
        Сумма ФОТ.
    """
    df = pd.read_excel(source_path, header=0)
    logger.info(f"FFOT: загружено {len(df)} строк из {source_path}")
    logger.info(f"FFOT: колонки: {list(df.columns)}")

    # Определяем колонку с типом записи
    if columns_config and columns_config.get("type"):
        type_col = columns_config["type"]
    else:
        type_col = None
        for col in df.columns:
            col_lower = col.lower().strip()
            if col_lower in ("типзаписи", "тип записи", "тип", "recordtype"):
                type_col = col
                break

    if not type_col:
        raise ValueError("Не найдена колонка с типом записи (ТипЗаписи)")

    # Фильтр: только ФактическийФОТ
    mask = df[type_col].astype(str).str.strip() == "ФактическийФОТ"
    df_ffot = df[mask]

    if df_ffot.empty:
        logger.warning("Нет строк с ТипЗаписи='ФактическийФОТ'")
        return 0.0

    logger.info(f"FFOT: найдено {len(df_ffot)} строк с ФактическийФОТ")

    # Определяем колонки Оклад и Премия
    if columns_config:
        oklad_col = columns_config.get("oklad")
        premia_col = columns_config.get("premia")
    else:
        oklad_col = None
        premia_col = None
        for col in df_ffot.columns:
            col_lower = col.lower().strip()
            if oklad_col is None and col_lower in ("оклад", "salary"):
                oklad_col = col
            if premia_col is None and col_lower in ("премия", "bonus"):
                premia_col = col

    total = 0.0
    if oklad_col:
        total += df_ffot[oklad_col].apply(_clean_numeric).sum()
        logger.info(f"FFOT: Оклад (колонка '{oklad_col}') = {df_ffot[oklad_col].apply(_clean_numeric).sum()}")
    if premia_col:
        total += df_ffot[premia_col].apply(_clean_numeric).sum()
        logger.info(f"FFOT: Премия (колонка '{premia_col}') = {df_ffot[premia_col].apply(_clean_numeric).sum()}")

    # Если не нашли Оклад/Премия — пробуем колонку Сумма
    if total == 0.0:
        amount_col = None
        for col in df_ffot.columns:
            col_lower = col.lower().strip()
            if col_lower in ("сумма", "amount"):
                amount_col = col
                break
        if amount_col:
            total = df_ffot[amount_col].apply(_clean_numeric).sum()
            logger.info(f"FFOT: Сумма (колонка '{amount_col}') = {total}")

    logger.info(f"FFOT: итоговая сумма = {total}")
    return total


async def write_ffot_to_template(
    source_path: str,
    template_path: str,
    month,
    year: int,
    password: str = "987456"
) -> dict:
    """
    Вычисляет ФактическийФОТ из выгрузки и записывает в шаблон.

    Логика:
    1. Читает source, фильтрует "ФактическийФОТ", суммирует Оклад+Премия
    2. Определяет месяц, предшествующий указанному (например, для 06 → Май)
    3. Ищет колонку с этим месяцем в строке 2 шаблона
    4. Ищет строку с "ФОТ фактический, руб." в колонке C
    5. Записывает значение в найденную ячейку

    Returns:
        dict с {ffot_value, cell (например "T46")}
    """
    # Расчёт суммы
    ffot_value = calculate_ffot_sum(source_path)

    # Открываем шаблон
    try:
        wb = openpyxl.load_workbook(template_path, data_only=True)
    except Exception:
        # Возможно зашифрован
        import tempfile
        import msoffcrypto
        with open(template_path, 'rb') as f:
            file = msoffcrypto.OfficeFile(f)
            if file.is_encrypted():
                file.load_key(password=password)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                    file.decrypt(tmp)
                    tmp_path = tmp.name
                wb = openpyxl.load_workbook(tmp_path, data_only=True)
                import os
                os.unlink(tmp_path)
            else:
                raise

    ws = wb["Отчетность БИТ 2026"]

    # Определяем предыдущий месяц
    prev_month_name = get_previous_month_name(month)

    # Ищем колонку
    col_idx = find_month_column(ws, prev_month_name)
    if col_idx is None:
        wb.close()
        raise ValueError(
            f"Не найден месяц '{prev_month_name}' в строке 2 шаблона"
        )

    # Ищем строку с "ФОТ фактический, руб."
    row_num = find_row_by_name(ws, 3, "ФОТ фактический, руб.")
    if row_num is None:
        wb.close()
        raise ValueError(
            "Не найдена строка 'ФОТ фактический, руб.' в колонке C шаблона"
        )

    # Записываем значение
    cell_ref = f"{get_column_letter(col_idx)}{row_num}"
    ws.cell(row=row_num, column=col_idx).value = ffot_value

    # Сохраняем
    wb.save(template_path)
    wb.close()
    logger.info(f"ФОТ записан: {ffot_value} в {cell_ref}")

    return {
        "ffot_value": ffot_value,
        "cell": cell_ref
    }
