import os
import shutil
import logging
import tempfile
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
import msoffcrypto

logger = logging.getLogger(__name__)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

async def read_excel_structure(file_path: str) -> dict:
    try:
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
            header_row = 2
            headers = [cell.value for cell in ws[header_row] if cell.value]
            sheets[sheet_name] = {
                "headers": headers,
                "rows_count": ws.max_row,
                "max_column": ws.max_column,
                "header_row": header_row
            }
        return {"status": "success", "result": {"sheets": sheets}}
    except Exception as e:
        logger.exception("read_excel_structure error")
        return {"status": "error", "error_message": str(e)}

async def apply_sheet_mapping(source_path: str, template_path: str, sheet_name: str, mapping: dict, month: str, year: int, password: str = "987456") -> dict:
    """
    Применяет маппинг к указанному листу.
    mapping может содержать:
        - source_columns: dict {target_col_index: source_col_name_or_expression}  (индексы колонок, начиная с 1)
        - append_to_end: bool (добавлять в конец)
        - filters: dict {source_col: value} - фильтровать строки по точному совпадению (строковое сравнение)
        - exclude_filters: dict {source_col: value} - исключить строки где value совпадает (строковое сравнение)
        - header_row: int (номер строки с заголовками в шаблоне, по умолчанию 2)
    """
    try:
        # 1. Копируем шаблон
        output_dir = os.path.dirname(template_path)
        output_filename = f"ДКП_10_-_{month}_{year}.xlsx"
        output_path = os.path.join(output_dir, output_filename)
        shutil.copy2(template_path, output_path)

        # 2. Расшифровка
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
        logger.info(f"Source rows before filters: {len(df_source)}")

        # 4. Применяем фильтры (с приведением к строке)
        filters = mapping.get("filters", {})
        exclude_filters = mapping.get("exclude_filters", {})

        if filters:
            for col, val in filters.items():
                if col in df_source.columns:
                    df_source = df_source[df_source[col].astype(str) == str(val)]
                    logger.info(f"Applied filter {col} = {val}, rows left: {len(df_source)}")
                else:
                    logger.warning(f"Filter column '{col}' not found in source")
        if exclude_filters:
            for col, val in exclude_filters.items():
                if col in df_source.columns:
                    df_source = df_source[df_source[col].astype(str) != str(val)]
                    logger.info(f"Applied exclude filter {col} != {val}, rows left: {len(df_source)}")
                else:
                    logger.warning(f"Exclude column '{col}' not found in source")

        if df_source.empty:
            return {"status": "error", "error_message": "No data after applying filters"}

        # 5. Открываем шаблон для записи
        wb = load_workbook(output_path)
        if sheet_name not in wb.sheetnames:
            return {"status": "error", "error_message": f"Sheet '{sheet_name}' not found in template"}
        ws = wb[sheet_name]

        # Удаляем все таблицы на листе, чтобы избежать повреждения
        if hasattr(ws, 'tables'):
            table_names = list(ws.tables.keys())
            for table_name in table_names:
                del ws.tables[table_name]
                logger.info(f"Removed table: {table_name}")

        # 6. Определяем номер строки с заголовками в шаблоне (по умолчанию 2)
        header_row = mapping.get("header_row", 2)
        if ws.cell(row=header_row, column=1).value is None:
            header_row = 1

        # 7. Подготавливаем данные для вставки
        source_cols = mapping.get("source_columns", {})
        # Преобразуем ключи (номера колонок) из строк в целые числа
        source_cols = {int(k): v for k, v in source_cols.items()}
        append = mapping.get("append_to_end", True)

        rows_to_insert = []
        for idx, row in df_source.iterrows():
            new_row = {}
            for target_col_idx, source_expr in source_cols.items():
                if source_expr == "{month} {year}":
                    new_row[target_col_idx] = f"{month} {year}"
                else:
                    if source_expr in df_source.columns:
                        new_row[target_col_idx] = row[source_expr]
                    else:
                        new_row[target_col_idx] = None
            rows_to_insert.append(new_row)

        if not rows_to_insert:
            return {"status": "error", "error_message": "No data to insert"}

        # 8. Вставляем строки
        if append:
            max_row = ws.max_row
            start_row = max_row + 1
            while start_row > header_row and ws.cell(row=start_row-1, column=1).value is None:
                start_row -= 1
            if start_row <= header_row:
                start_row = header_row + 1
        else:
            if ws.max_row > header_row:
                ws.delete_rows(header_row + 1, ws.max_row - header_row)
            start_row = header_row + 1

        for i, row_dict in enumerate(rows_to_insert, start=start_row):
            for col_idx, value in row_dict.items():
                if value is not None:
                    ws.cell(row=i, column=col_idx).value = value

        wb.save(output_path)

        return {"status": "success", "output_path": output_path, "rows_added": len(rows_to_insert)}
    except Exception as e:
        logger.exception("apply_sheet_mapping error")
        return {"status": "error", "error_message": str(e)}