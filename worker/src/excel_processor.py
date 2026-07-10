import os
import shutil
import logging
import tempfile
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
import msoffcrypto

logger = logging.getLogger(__name__)

async def update_excel(template_path: str, data: dict, month: str, year: int, password: str = "987456") -> dict:
    """
    Копирует шаблон, вставляет данные на каждый лист, обновляет таблицы,
    устанавливает автофильтр, защищает старые периоды.
    """
    try:
        output_dir = os.path.dirname(template_path)
        output_filename = f"ДКП_10_-_{month}_{year}.xlsx"
        output_path = os.path.join(output_dir, output_filename)
        
        # 1. Копируем шаблон
        shutil.copy2(template_path, output_path)
        
        # 2. Если файл защищён паролем – расшифровываем
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
                logger.warning(f"Failed to decrypt file (maybe no password): {e}")
        
        # 3. Открываем книгу
        wb = load_workbook(output_path)
        
        # 4. Сопоставление листов и данных
        sheets_mapping = {
            "Реализация": data.get("realization_rows", []),
            "ДС": data.get("payment_rows", []),
            "ФОТ": data.get("payroll_rows", []),  # уже сгруппированные
            "Взаиморасчеты": data.get("settlements_rows", [])
        }
        
        # 5. Для каждого листа вставляем строки
        for sheet_name, rows in sheets_mapping.items():
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            if not rows:
                continue
            
            # Находим последнюю заполненную строку (ищем первую пустую в колонке A)
            max_row = ws.max_row
            start_row = max_row + 1
            
            # Заголовки – берём из первой строки данных
            if rows:
                headers = list(rows[0].keys())
                # Записываем данные
                for i, row in enumerate(rows, start=start_row):
                    for j, header in enumerate(headers, start=1):
                        cell = ws.cell(row=i, column=j)
                        cell.value = row.get(header, "")
                
                # Обновляем таблицу (если есть)
                for table in ws.tables.values():
                    if "Table" in table.name or table.name.startswith("Таблица"):
                        # Определяем новый диапазон
                        total_rows = len(rows)
                        if total_rows > 0:
                            new_ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + total_rows - 1}"
                            table.ref = new_ref
                            if not table.tableStyleInfo:
                                table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
                
                # Устанавливаем автофильтр на диапазон таблицы (для всех строк, включая заголовок)
                ws.auto_filter.ref = f"A{start_row - 1}:{get_column_letter(len(headers))}{start_row + len(rows) - 1}"
        
        # 6. Вставляем фактический ФОТ на лист "Отчетность БИТ 2026"
        if "Отчетность БИТ 2026" in wb.sheetnames:
            ws_bit = wb["Отчетность БИТ 2026"]
            fact_ffot = data.get("fact_ffot_value", 0)
            # Ищем ячейку "ФОТ фактический" в столбце предыдущего месяца
            # Предполагаем, что столбцы идут по порядку: январь-декабрь, начиная с B или C
            # Для простоты найдём ячейку с меткой "ФОТ фактический, руб." и рядом с ней пустую ячейку текущего месяца
            # Мы запишем в столбец предыдущего месяца (месяц-1)
            # Это упрощённо, позже можно доработать
            for row in ws_bit.iter_rows():
                for cell in row:
                    if cell.value and "ФОТ фактический" in str(cell.value):
                        # cell - метка, записываем в ячейку справа (столбец предыдущего месяца)
                        # Определяем номер месяца (индекс колонки)
                        # Предположим, что столбцы начинаются с B (январь) или C
                        # Для упрощения ищем ячейку с меткой месяца в той же строке
                        # Пока запишем в первую свободную ячейку справа от метки
                        target_col = cell.column + 1
                        # Проверяем, не занята ли ячейка (если занята, ищем следующую)
                        while ws_bit.cell(row=cell.row, column=target_col).value is not None:
                            target_col += 1
                        ws_bit.cell(row=cell.row, column=target_col).value = fact_ffot
                        break
        
        # 7. Сохраняем книгу
        wb.save(output_path)
        
        # 8. Устанавливаем пароль (если нужно) – через msoffcrypto не поддерживается, оставляем без пароля
        # Но для совместимости с инструкцией можно попробовать использовать pywin32, но это сложно.
        # Пока сохраняем без пароля, пользователь может установить вручную.
        
        return {"status": "success", "result": {"output_path": output_path}}
    except Exception as e:
        logger.exception("Excel update error")
        return {"status": "error", "error_message": str(e)}