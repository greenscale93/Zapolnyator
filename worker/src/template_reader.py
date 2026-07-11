"""
Чтение данных из шаблона Excel-отчёта (через python-calamine).

Содержит:
- get_template_offices — список офисов из шаблона
- find_row_by_name — поиск строки по тексту в колонке
- find_month_column — поиск колонки месяца в шапке
- read_cell_at — чтение значения из ячейки
"""
import logging
import os
import tempfile
from typing import Optional, List

from python_calamine import CalamineWorkbook
import msoffcrypto

logger = logging.getLogger(__name__)


def _decrypt_if_needed(template_path: str, password: str = "987456") -> str:
    """Расшифровывает файл если нужно, возвращает путь к расшифрованной копии."""
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template file not found: {template_path}")

    try:
        with open(template_path, 'rb') as f:
            office_file = msoffcrypto.OfficeFile(f)
            if office_file.is_encrypted():
                office_file.load_key(password=password)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                office_file.decrypt(tmp)
                tmp.close()
                logger.info(f"Decrypted: {tmp.name}")
                return tmp.name
    except Exception:
        pass
    return template_path


def _open_sheet(template_path: str, sheet_name: str) -> List[List]:
    """Открывает лист и возвращает 2D-список данных (как to_python)."""
    decrypted = _decrypt_if_needed(template_path)
    try:
        wb = CalamineWorkbook.from_path(decrypted)
        names = wb.sheet_names
        if sheet_name not in names:
            raise ValueError(f"Лист '{sheet_name}' не найден. Доступны: {names}")
        sheet = wb.get_sheet_by_name(sheet_name)
        data = sheet.to_python()
        return data
    finally:
        if decrypted != template_path and os.path.exists(decrypted):
            try:
                os.unlink(decrypted)
            except Exception:
                pass


def open_workbook_and_sheet(
    template_path: str,
    sheet_name: str = "Отчетность БИТ 2026",
    **kwargs
):
    """
    Открывает лист и возвращает (data, sheet_name) где data — 2D-список.
    Для обратной совместимости — вместо (wb, ws) теперь (data, name).
    """
    data = _open_sheet(template_path, sheet_name)
    return data, sheet_name


def get_template_offices(template_path: str) -> list:
    """Читает список офисов из шаблона."""
    data = _open_sheet(template_path, "Отчетность БИТ 2026")
    offices = set()
    for row in range(16, 33):
        if row <= len(data) and len(data[row - 1]) > 2:
            val = data[row - 1][2]  # 0-based: column 3
            if val and str(val).strip():
                offices.add(str(val).strip())
    for row in range(34, 36):
        if row <= len(data) and len(data[row - 1]) > 2:
            val = data[row - 1][2]
            if val and str(val).strip():
                offices.add(str(val).strip())
    return sorted(list(offices))


def find_row_by_name(data, column: int, name: str) -> Optional[int]:
    """
    Находит номер строки (1-based) по тексту в колонке.
    data — 2D-список из calamine to_python().
    """
    col_idx = column - 1  # 1-based → 0-based
    for row_idx, row in enumerate(data):
        if col_idx < len(row) and row[col_idx] is not None:
            if name.strip() in str(row[col_idx]).strip():
                result = row_idx + 1
                logger.info(f"Строка '{name}' найдена в {chr(64 + column) if column <= 26 else '?'}{result}")
                return result
    logger.warning(f"Строка '{name}' не найдена в колонке {column}")
    return None


def find_month_column(data, month_name: str, search_row: int = 2) -> Optional[int]:
    """
    Находит номер колонки (1-based) по названию месяца в строке.
    data — 2D-список из calamine to_python().
    """
    if search_row > len(data):
        logger.warning(f"Строка {search_row} вне данных (всего {len(data)} строк)")
        return None

    row_data = data[search_row - 1]
    for col_idx, val in enumerate(row_data):
        if val is not None and month_name.strip() in str(val).strip():
            result = col_idx + 1
            logger.info(f"Месяц '{month_name}' найден в колонке {result}")
            return result
    logger.warning(f"Месяц '{month_name}' не найден в строке {search_row}")
    return None


def read_cell_at(data, row: int, column: int):
    """
    Читает значение из ячейки (row, column — 1-based).
    calamine автоматически заполняет объединённые ячейки значением
    из верхней левой — дополнительная обработка не нужна.
    """
    r, c = row - 1, column - 1
    if r < len(data) and c < len(data[r]):
        return data[r][c]
    return None

