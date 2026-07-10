import csv
import os
import logging
import re
import json
from io import StringIO

logger = logging.getLogger(__name__)

def extract_table_data(parsed_structure):
    """
    Извлекает табличные данные из структуры MXL.
    Ожидает, что parsed_structure — это словарь с ключами 'columns' и 'data'.
    """
    if isinstance(parsed_structure, dict):
        if 'data' in parsed_structure:
            return parsed_structure['data']
        if 'result' in parsed_structure and isinstance(parsed_structure['result'], dict):
            return parsed_structure['result'].get('data', [])
    return []

async def parse_mxl(file_path: str) -> dict:
    """
    Парсит MXL-файл (текстовый формат 1С) и возвращает данные.
    """
    if not os.path.exists(file_path):
        return {"status": "error", "error_message": f"File not found: {file_path}"}
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Ищем все строки вида {"#","значение"} или {"#","значение1","значение2"}
        pattern = r'\{"#"\s*,\s*"([^"]*)"(?:\s*,\s*"([^"]*)")?\s*\}'
        matches = re.findall(pattern, content)
        
        if not matches:
            return {"status": "error", "error_message": "No data found in MXL file"}
        
        # Первая строка — заголовки
        headers = []
        data_rows = []
        is_header = True
        
        for match in matches:
            if is_header:
                # Первая строка — это заголовки
                headers = [m for m in match if m]
                is_header = False
            else:
                # Остальные — данные
                row = {}
                for i, value in enumerate(match):
                    if i < len(headers):
                        row[headers[i]] = value
                if row:
                    data_rows.append(row)
        
        return {
            "status": "success",
            "result": {
                "data": data_rows,
                "columns": headers,
                "total_rows": len(data_rows)
            }
        }
    except Exception as e:
        logger.exception("MXL parsing error")
        return {"status": "error", "error_message": str(e)}

async def convert_mxl_to_csv(file_path: str) -> dict:
    """
    Конвертирует MXL-файл в CSV и сохраняет рядом.
    Возвращает путь к CSV и сами данные.
    """
    if not os.path.exists(file_path):
        return {"status": "error", "error_message": f"File not found: {file_path}"}
    
    try:
        parsed = await parse_mxl(file_path)
        if parsed.get("status") == "error":
            return parsed
        
        data = extract_table_data(parsed)
        
        if not data:
            return {"status": "error", "error_message": "No data extracted from MXL"}
        
        # Очищаем данные от ключей None
        cleaned_data = []
        for row in data:
            if isinstance(row, dict):
                cleaned_row = {k: v for k, v in row.items() if k is not None}
                cleaned_data.append(cleaned_row)
            else:
                cleaned_data.append(row)
        data = cleaned_data
        
        # Определяем колонки
        if data and isinstance(data[0], dict):
            columns = list(data[0].keys())
        else:
            columns = []
        
        # Генерируем CSV
        output = StringIO()
        if columns:
            writer = csv.DictWriter(output, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for row in data:
                if isinstance(row, dict):
                    clean_row = {k: v for k, v in row.items() if k is not None}
                    writer.writerow(clean_row)
                else:
                    writer.writerow(row)
        else:
            writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
            for row in data:
                if isinstance(row, dict):
                    writer.writerow(list(row.values()))
                else:
                    writer.writerow(row)
        
        csv_data = output.getvalue()
        
        # Сохраняем CSV рядом с исходным файлом
        csv_path = file_path + ".csv"
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write(csv_data)
        
        return {
            "status": "success",
            "result": {
                "csv_data": csv_data,
                "csv_path": csv_path,
                "rows": len(data),
                "columns": columns,
                "size_bytes": len(csv_data.encode('utf-8'))
            }
        }
    except Exception as e:
        logger.exception("MXL to CSV conversion error")
        return {"status": "error", "error_message": str(e)}