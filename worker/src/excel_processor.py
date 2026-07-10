import os
import shutil
import logging
import tempfile
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
import msoffcrypto

logger = logging.getLogger(__name__)

async def read_excel_structure(file_path: str) -> dict:
    """Возвращает список листов и их колонки (из первой строки)"""
    try:
        # Если файл защищён, пытаемся расшифровать
        if os.path.exists(file_path):
            # Проверяем, не зашифрован ли
            try:
                with open(file_path, 'rb') as f:
                    file = msoffcrypto.OfficeFile(f)
                    if file.is_encrypted():
                        # Попробуем стандартный пароль
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
            # Берём первую строку как заголовки
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
    Записывает данные на указанные листы.
    sheets_data: {sheet_name: [list of dict]}, где каждый dict - строка с колонками.
    """
    try:
        if not output_path:
            output_dir = os.path.dirname(template_path)
            output_path = os.path.join(output_dir, "filled_report.xlsx")
        
        # 1. Копируем шаблон
        shutil.copy2(template_path, output_path)
        
        # 2. Если файл защищён паролем – расшифровываем
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
            logger.warning(f"Failed to decrypt file (maybe no password): {e}")
        
        # 3. Открываем книгу
        wb = load_workbook(output_path)
        
        # 4. Для каждого листа в sheets_data записываем строки
        for sheet_name, rows in sheets_data.items():
            if sheet_name not in wb.sheetnames:
                logger.warning(f"Sheet {sheet_name} not found in template, skipping")
                continue
            ws = wb[sheet_name]
            if not rows:
                continue
            
            # Находим первую пустую строку (проверяем колонку A)
            max_row = ws.max_row
            start_row = max_row + 1
            # Если в колонке A есть данные, ищем дальше (на случай, если последние строки пустые)
            while ws.cell(row=start_row, column=1).value is not None:
                start_row += 1
            
            # Заголовки – из первой строки данных (берём ключи первого dict)
            headers = list(rows[0].keys())
            # Записываем данные
            for i, row_dict in enumerate(rows, start=start_row):
                for j, header in enumerate(headers, start=1):
                    cell = ws.cell(row=i, column=j)
                    cell.value = row_dict.get(header, "")
            
            # Обновляем таблицу (если есть)
            for table in ws.tables.values():
                # Определяем новый диапазон (от заголовка до последней строки)
                total_rows = len(rows)
                if total_rows > 0:
                    new_ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + total_rows - 1}"
                    table.ref = new_ref
                    if not table.tableStyleInfo:
                        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
            
            # Устанавливаем автофильтр
            ws.auto_filter.ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + len(rows) - 1}"
        
        # 5. Сохраняем книгу
        wb.save(output_path)
        
        # 6. Попробуем установить пароль (через msoffcrypto, но openpyxl не поддерживает запись с паролем)
        # Поэтому оставляем без пароля; можно добавить позже через сторонние утилиты.
        
        return {"status": "success", "output_path": output_path}
    except Exception as e:
        logger.exception("write_excel_data error")
        return {"status": "error", "error_message": str(e)}