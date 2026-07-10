import os
import shutil
import logging
import tempfile
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
import msoffcrypto

logger = logging.getLogger(__name__)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (для совместимости) ==========

async def read_excel_structure(file_path: str) -> dict:
    """Возвращает список листов и их колонки (из первой строки)"""
    try:
        # Если файл защищён, пытаемся расшифровать
        if os.path.exists(file_path):
            try:
                with open(file_path, 'rb') as f:
                    file = msoffcrypto.OfficeFile(f)
                    if file.is_encrypted():
                        try:
                            file.load_key(password="987456")
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                                file.decrypt(tmp)
                                tmp_path = tmp.name
                            wb = load_workbook(tmp_path, data_only=True)
                            os.unlink(tmp_path)
                        except:
                            return {"status": "error", "error_message": "Cannot decrypt file with default password"}
                    else:
                        wb = load_workbook(file_path, data_only=True)
            except:
                wb = load_workbook(file_path, data_only=True)
        else:
            return {"status": "error", "error_message": "File not found"}
        
        sheets = {}
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            headers = [cell.value for cell in ws[1] if cell.value]
            sheets[sheet_name] = {
                "headers": headers,
                "rows_count": ws.max_row,
                "max_column": ws.max_column
            }
        return {"status": "success", "result": {"sheets": sheets}}
    except Exception as e:
        logger.exception("read_excel_structure error")
        return {"status": "error", "error_message": str(e)}

async def write_excel_data(template_path: str, sheets_data: dict, password: str = "987456", output_path: str = None) -> dict:
    """
    (Заглушка для совместимости. Не используется в новом подходе.)
    """
    return {"status": "error", "error_message": "write_excel_data is deprecated, use apply_sheet_mapping instead"}

# ========== ОСНОВНАЯ ФУНКЦИЯ ДЛЯ МАППИНГА ==========

async def apply_sheet_mapping(source_path: str, template_path: str, sheet_name: str, mapping: dict, month: str, year: int, password: str = "987456") -> dict:
    """
    Применяет маппинг к указанному листу.
    mapping должен содержать:
        - source_columns: dict {target_col: source_col_or_expression}
        - append_to_end: bool (добавлять в конец)
    """
    try:
        # 1. Копируем шаблон
        output_dir = os.path.dirname(template_path)
        output_filename = f"ДКП_10_-_{month}_{year}.xlsx"
        output_path = os.path.join(output_dir, output_filename)
        shutil.copy2(template_path, output_path)

        # 2. Расшифровка, если есть пароль
        if password:
            try:
                with open(output_path, 'rb') as f:
                    file = msoffcrypto.OfficeFile(f)
                    if file.is_encrypted():
                        file.load_key(password=password)
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                            file.decrypt(tmp)
                            tmp_path = tmp.name
                        shutil.move(tmp_path, output_path)
            except Exception as e:
                logger.warning(f"Decrypt failed: {e}")

        # 3. Читаем источник (Excel) в DataFrame
        df_source = pd.read_excel(source_path, header=0)

        # 4. Открываем шаблон для записи
        wb = load_workbook(output_path)
        if sheet_name not in wb.sheetnames:
            return {"status": "error", "error_message": f"Sheet '{sheet_name}' not found in template"}
        ws = wb[sheet_name]

        # 5. Подготавливаем данные для вставки
        source_cols = mapping.get("source_columns", {})
        append = mapping.get("append_to_end", True)

        target_cols = list(source_cols.keys())
        col_mapping = {}
        for target_col, source_expr in source_cols.items():
            col_mapping[target_col] = source_expr

        # 6. Извлекаем данные из источника
        rows_to_insert = []
        for idx, row in df_source.iterrows():
            new_row = {}
            for target_col, source_expr in col_mapping.items():
                if source_expr == "{month} {year}":
                    new_row[target_col] = f"{month} {year}"
                else:
                    if source_expr in df_source.columns:
                        new_row[target_col] = row[source_expr]
                    else:
                        new_row[target_col] = None
            rows_to_insert.append(new_row)

        if not rows_to_insert:
            return {"status": "error", "error_message": "No data to insert"}

        # 7. Вставляем строки в лист (без таблиц и автофильтра)
        if append:
            max_row = ws.max_row
            start_row = max_row + 1
        else:
            # Если append_to_end = false, очищаем лист, оставляя только заголовки
            if ws.max_row > 1:
                ws.delete_rows(2, ws.max_row - 1)
            start_row = 2

        headers = list(rows_to_insert[0].keys())
        for i, row_dict in enumerate(rows_to_insert, start=start_row):
            for j, header in enumerate(headers, start=1):
                cell = ws.cell(row=i, column=j)
                cell.value = row_dict.get(header)

        # 8. Сохраняем книгу (НЕ трогаем таблицы и автофильтр)
        wb.save(output_path)

        return {"status": "success", "output_path": output_path}
    except Exception as e:
        logger.exception("apply_sheet_mapping error")
        return {"status": "error", "error_message": str(e)}