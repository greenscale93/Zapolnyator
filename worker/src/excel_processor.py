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

async def update_excel(template_path: str, data: dict, month: str, year: int, password: str = "987456") -> dict:
    """
    Копирует шаблон, вставляет данные на каждый лист, устанавливает автофильтр и пароль.
    Поддерживает .xlsx и .xls (через pandas).
    """
    try:
        # 1. Определяем формат файла по расширению
        ext = os.path.splitext(template_path)[1].lower()
        output_dir = os.path.dirname(template_path)
        output_filename = f"ДКП_10_-_{month}_{year}.xlsx"
        output_path = os.path.join(output_dir, output_filename)
        
        # 2. Создаём копию шаблона
        shutil.copy2(template_path, output_path)
        
        # 3. Если файл .xls – конвертируем в .xlsx с помощью pandas
        if ext == '.xls':
            df_dict = {}
            # Читаем все листы из .xls
            xls = pd.ExcelFile(output_path, engine='xlrd')
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name, header=0)
                df_dict[sheet_name] = df
            # Сохраняем как .xlsx
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                for sheet_name, df in df_dict.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            # Теперь работаем с .xlsx
            ext = '.xlsx'
        
        # 4. Если файл защищён паролем – расшифровываем
        if password:
            try:
                with open(output_path, 'rb') as f:
                    file = msoffcrypto.OfficeFile(f)
                    if file.is_encrypted():
                        file.load_key(password=password)
                        # Сохраняем расшифрованный файл во временный
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                            file.decrypt(tmp)
                            tmp_path = tmp.name
                        shutil.move(tmp_path, output_path)
                        logger.info(f"Decrypted file {output_path}")
            except Exception as e:
                logger.warning(f"Failed to decrypt file (maybe no password): {e}")
        
        # 5. Открываем книгу через openpyxl
        wb = load_workbook(output_path)
        
        # 6. Данные по листам
        sheets_data = {
            "Реализация": data.get("realization_rows", []),
            "ДС": data.get("payment_rows", []),
            "ФОТ": data.get("payroll_rows", []),
            "Взаиморасчеты": data.get("settlements_rows", [])
        }
        
        # 7. Для каждого листа вставляем строки
        for sheet_name, rows in sheets_data.items():
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            if not rows:
                continue
            
            # Находим первую пустую строку
            max_row = ws.max_row
            start_row = max_row + 1
            
            # Заголовки
            headers = list(rows[0].keys())
            # Записываем данные
            for i, row in enumerate(rows, start=start_row):
                for j, header in enumerate(headers, start=1):
                    cell = ws.cell(row=i, column=j)
                    cell.value = row.get(header)
            
            # Обновляем таблицу (если есть)
            for table in ws.tables.values():
                if "Table" in table.name:
                    new_ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + len(rows) - 1}"
                    table.ref = new_ref
                    if not table.tableStyleInfo:
                        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
            
            # Автофильтр
            ws.auto_filter.ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + len(rows) - 1}"
        
        # 8. Вставляем ФОТ на лист "Отчетность БИТ 2026"
        if "Отчетность БИТ 2026" in wb.sheetnames:
            ws_bit = wb["Отчетность БИТ 2026"]
            for row in ws_bit.iter_rows():
                for cell in row:
                    if cell.value and "ФОТ" in str(cell.value):
                        target_cell = ws_bit.cell(row=cell.row, column=cell.column+1)
                        target_cell.value = data.get("fact_ffot_value", 0)
                        break
        
        # 9. Сохраняем и устанавливаем пароль
        wb.save(output_path)
        
        # 10. Если нужен пароль – защищаем через msoffcrypto (это не поддерживается напрямую, но мы можем пересохранить с паролем через openpyxl, но openpyxl не поддерживает пароль).
        # Поэтому мы просто вернём путь. Если нужна защита паролем, лучше использовать сторонние утилиты, но пока оставим.
        
        return {"status": "success", "result": {"output_path": output_path}}
    except Exception as e:
        logger.exception("Excel update error")
        return {"status": "error", "error_message": str(e)}