import os
import shutil
import logging
import tempfile
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils.cell import range_boundaries
import msoffcrypto

logger = logging.getLogger(__name__)

def get_top_left_cell(worksheet, cell):
    """Возвращает верхнюю левую ячейку для объединённого диапазона, если cell объединена."""
    if cell.coordinate in worksheet.merged_cells:
        for merged_range in worksheet.merged_cells.ranges:
            if cell.coordinate in merged_range:
                return worksheet.cell(row=merged_range.min_row, column=merged_range.min_col)
    return cell

async def update_excel(template_path: str, data: dict, month: str, year: int, password: str = "987456") -> dict:
    try:
        ext = os.path.splitext(template_path)[1].lower()
        output_dir = os.path.dirname(template_path)
        output_filename = f"ДКП_10_-_{month}_{year}.xlsx"
        output_path = os.path.join(output_dir, output_filename)

        shutil.copy2(template_path, output_path)

        # Конвертация .xls -> .xlsx
        if ext == '.xls':
            xls = pd.ExcelFile(output_path, engine='xlrd')
            df_dict = {sheet_name: pd.read_excel(xls, sheet_name=sheet_name, header=0) for sheet_name in xls.sheet_names}
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                for sheet_name, df in df_dict.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            ext = '.xlsx'

        # Расшифровка
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
                        logger.info(f"Decrypted file {output_path}")
            except Exception as e:
                logger.warning(f"Failed to decrypt file: {e}")

        wb = load_workbook(output_path)

        sheets_data = {
            "Реализация": data.get("realization_rows", []),
            "ДС": data.get("payment_rows", []),
            "ФОТ": data.get("payroll_rows", []),
            "Взаиморасчеты": data.get("settlements_rows", [])
        }

        for sheet_name, rows in sheets_data.items():
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            if not rows:
                continue

            max_row = ws.max_row
            start_row = max_row + 1
            headers = list(rows[0].keys())
            for i, row in enumerate(rows, start=start_row):
                for j, header in enumerate(headers, start=1):
                    cell = ws.cell(row=i, column=j)
                    # Если ячейка объединена, пропускаем запись (записываем только в главную)
                    if cell.coordinate in ws.merged_cells:
                        continue
                    cell.value = row.get(header)

            # Обновление таблиц
            for table in ws.tables.values():
                if "Table" in table.name:
                    new_ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + len(rows) - 1}"
                    table.ref = new_ref

            ws.auto_filter.ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + len(rows) - 1}"

        # Вставка ФОТ на лист "Отчетность БИТ 2026"
        if "Отчетность БИТ 2026" in wb.sheetnames:
            ws_bit = wb["Отчетность БИТ 2026"]
            fot_value = data.get("fact_ffot_value", 0)
            for row in ws_bit.iter_rows():
                for cell in row:
                    if cell.value and "ФОТ" in str(cell.value):
                        target_cell = ws_bit.cell(row=cell.row, column=cell.column+1)
                        # Проверяем объединение
                        if target_cell.coordinate in ws_bit.merged_cells:
                            target_cell = get_top_left_cell(ws_bit, target_cell)
                        try:
                            target_cell.value = fot_value
                        except AttributeError:
                            # fallback
                            ws_bit.cell(row=target_cell.row, column=target_cell.column).value = fot_value
                        break

        wb.save(output_path)

        return {"status": "success", "result": {"output_path": output_path}}
    except Exception as e:
        logger.exception("Excel update error")
        return {"status": "error", "error_message": str(e)}