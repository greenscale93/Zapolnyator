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
    mapping содержит:
        - filters: dict {col_name: value} — строки должны соответствовать всем фильтрам
        - exclude_filters: dict {col_name: [values]} — строки, где col_name in values, исключаются
        - column_mapping: dict {col_number: source_col_or_expression} — куда писать
        - append_to_end: bool
    """
    try:
        output_dir = os.path.dirname(template_path)
        output_filename = f"ДКП_10_-_{month}_{year}.xlsx"
        output_path = os.path.join(output_dir, output_filename)
        shutil.copy2(template_path, output_path)

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

        # Читаем источник
        df_source = pd.read_excel(source_path, header=0)

        # Применяем фильтры
        filters = mapping.get("filters", {})
        for col, value in filters.items():
            if col in df_source.columns:
                df_source = df_source[df_source[col] == value]

        # Исключаем
        exclude_filters = mapping.get("exclude_filters", {})
        for col, values in exclude_filters.items():
            if col in df_source.columns:
                df_source = df_source[~df_source[col].isin(values)]

        # Открываем шаблон
        wb = load_workbook(output_path)
        if sheet_name not in wb.sheetnames:
            return {"status": "error", "error_message": f"Sheet '{sheet_name}' not found"}
        ws = wb[sheet_name]

        # Получаем маппинг колонок {номер_колонки: источник}
        col_mapping = mapping.get("column_mapping", {})
        append = mapping.get("append_to_end", True)

        # Определяем, куда вставлять
        if append:
            max_row = ws.max_row
            start_row = max_row + 1
        else:
            if ws.max_row > 1:
                ws.delete_rows(2, ws.max_row - 1)
            start_row = 2

        # Проходим по строкам источника и пишем
        for row_idx, source_row in df_source.iterrows():
            for col_num_str, source_expr in col_mapping.items():
                col_num = int(col_num_str)
                if source_expr == "{month} {year}":
                    value = f"{month} {year}"
                elif source_expr in df_source.columns:
                    value = source_row[source_expr]
                else:
                    # Если source_expr — константа
                    value = source_expr
                cell = ws.cell(row=start_row + row_idx, column=col_num)
                cell.value = value

        wb.save(output_path)
        return {"status": "success", "output_path": output_path}
    except Exception as e:
        logger.exception("apply_sheet_mapping error")
        return {"status": "error", "error_message": str(e)}