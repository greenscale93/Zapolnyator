import os
import shutil
import logging
import tempfile
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
import msoffcrypto

logger = logging.getLogger(__name__)

async def read_excel_structure(file_path: str) -> dict:
    """Возвращает структуру Excel-файла: листы, заголовки, количество строк."""
    try:
        wb = load_workbook(file_path, data_only=True)
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

async def apply_sheet_mapping(source_path: str, template_path: str, sheet_name: str, mapping: dict, month: str, year: int, password: str = "987456") -> dict:
    """
    Применяет маппинг к указанному листу.
    mapping должен содержать:
        - source_columns: dict {target_col: source_col_or_expression}
        - append_to_end: bool (добавлять в конец)
    """
    try:
        logger.info(f"Applying mapping for sheet {sheet_name} from {source_path} to {template_path}")
        logger.info(f"Mapping: {mapping}")

        # 1. Копируем шаблон
        output_dir = os.path.dirname(template_path)
        output_filename = f"ДКП_10_-_{month}_{year}.xlsx"
        output_path = os.path.join(output_dir, output_filename)
        shutil.copy2(template_path, output_path)
        logger.info(f"Copied template to {output_path}")

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
                        logger.info("Decrypted file")
            except Exception as e:
                logger.warning(f"Decrypt failed: {e}")

        # 3. Читаем источник (Excel) в DataFrame
        df_source = pd.read_excel(source_path, header=0)
        logger.info(f"Source data: {len(df_source)} rows, columns: {df_source.columns.tolist()}")

        # 4. Открываем шаблон для записи
        wb = load_workbook(output_path)
        if sheet_name not in wb.sheetnames:
            return {"status": "error", "error_message": f"Sheet '{sheet_name}' not found in template"}
        ws = wb[sheet_name]
        logger.info(f"Sheet '{sheet_name}' found, current max row: {ws.max_row}")

        # 5. Подготавливаем данные для вставки
        source_cols = mapping.get("source_columns", {})
        append = mapping.get("append_to_end", True)

        # Определяем соответствие
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
                        val = row[source_expr]
                        # Если значение NaN, заменяем на None
                        if pd.isna(val):
                            val = None
                        new_row[target_col] = val
                    else:
                        new_row[target_col] = None
            rows_to_insert.append(new_row)

        if not rows_to_insert:
            return {"status": "error", "error_message": "No data to insert"}
        logger.info(f"Prepared {len(rows_to_insert)} rows for insertion")

        # 7. Вставляем строки в лист
        if append:
            max_row = ws.max_row
            start_row = max_row + 1
        else:
            # Очищаем лист, оставляя только заголовки
            if ws.max_row > 1:
                ws.delete_rows(2, ws.max_row - 1)
            start_row = 2

        headers = list(rows_to_insert[0].keys())
        for i, row_dict in enumerate(rows_to_insert, start=start_row):
            for j, header in enumerate(headers, start=1):
                cell = ws.cell(row=i, column=j)
                cell.value = row_dict.get(header)

        # 8. Обновляем таблицу (если есть)
        for table in ws.tables.values():
            if "Table" in table.name or table.name.startswith("Таблица"):
                total_rows = len(rows_to_insert)
                if total_rows > 0:
                    new_ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + total_rows - 1}"
                    table.ref = new_ref
                    if not table.tableStyleInfo:
                        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)

        # 9. Автофильтр
        ws.auto_filter.ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + len(rows_to_insert) - 1}"

        # 10. Сохраняем
        wb.save(output_path)
        logger.info(f"Saved file to {output_path}")

        return {"status": "success", "output_path": output_path}
    except Exception as e:
        logger.exception("apply_sheet_mapping error")
        return {"status": "error", "error_message": str(e)}