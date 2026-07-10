import csv
import os
import logging
import re
import json
from io import StringIO

logger = logging.getLogger(__name__)

def fix_encoding(s):
    """Принудительно перекодирует строку из cp1251 в utf-8, если нужно."""
    if isinstance(s, str):
        try:
            # Проверяем, есть ли символы, характерные для cp1251
            if any(ord(c) > 127 for c in s):
                return s.encode('cp1251').decode('utf-8', errors='ignore')
        except:
            pass
    return s

def extract_table_data(parsed_structure):
    if isinstance(parsed_structure, dict):
        if 'data' in parsed_structure:
            return parsed_structure['data']
        if 'result' in parsed_structure and isinstance(parsed_structure['result'], dict):
            return parsed_structure['result'].get('data', [])
    return []

async def parse_mxl(file_path: str) -> dict:
    if not os.path.exists(file_path):
        return {"status": "error", "error_message": f"File not found: {file_path}"}
    
    try:
        # Принудительно пробуем cp1251, затем utf-8
        encodings = ['cp1251', 'windows-1251', 'utf-8']
        content = None
        used_encoding = None
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc, errors='ignore') as f:
                    content = f.read()
                    used_encoding = enc
                    break
            except:
                continue
        if content is None:
            return {"status": "error", "error_message": "Cannot detect encoding"}
        logger.info(f"Used encoding for MXL: {used_encoding}")
        
        # Если использовали cp1251, перекодируем в utf-8
        if used_encoding.lower() in ['cp1251', 'windows-1251']:
            content = content.encode('cp1251').decode('utf-8', errors='ignore')
            logger.info("Re-encoded from cp1251 to utf-8")
        
        # Ищем все строки вида {"#","значение"} или {"#","значение1","значение2"}
        pattern = r'\{"#"\s*,\s*"([^"]*)"(?:\s*,\s*"([^"]*)")?\s*\}'
        matches = re.findall(pattern, content)
        
        if not matches:
            return {"status": "error", "error_message": "No data found in MXL file"}
        
        headers = []
        data_rows = []
        is_header = True
        
        for match in matches:
            # Перекодируем каждую строку в match
            decoded_match = tuple(fix_encoding(s) for s in match)
            if is_header:
                headers = [s for s in decoded_match if s]
                is_header = False
            else:
                row = {}
                for i, value in enumerate(decoded_match):
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
    if not os.path.exists(file_path):
        return {"status": "error", "error_message": f"File not found: {file_path}"}
    
    try:
        parsed = await parse_mxl(file_path)
        if parsed.get("status") == "error":
            return parsed
        
        data = extract_table_data(parsed)
        
        if not data:
            return {"status": "error", "error_message": "No data extracted from MXL"}
        
        # Применяем fix_encoding ко всем строкам в данных и заголовкам
        fixed_data = []
        for row in data:
            if isinstance(row, dict):
                fixed_row = {}
                for k, v in row.items():
                    fixed_k = fix_encoding(k)
                    fixed_v = fix_encoding(v)
                    fixed_row[fixed_k] = fixed_v
                fixed_data.append(fixed_row)
            else:
                fixed_data.append(row)
        data = fixed_data
        
        if data and isinstance(data[0], dict):
            columns = list(data[0].keys())
        else:
            columns = []
        
        # Генерируем CSV в UTF-8 с BOM
        output = StringIO()
        if columns:
            writer = csv.DictWriter(output, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            for row in data:
                if isinstance(row, dict):
                    writer.writerow(row)
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
        
        csv_path = file_path + ".csv"
        with open(csv_path, 'w', encoding='utf-8-sig') as f:
            f.write(csv_data)
        
        return {
            "status": "success",
            "result": {
                "csv_data": csv_data,
                "csv_path": csv_path,
                "rows": len(data),
                "columns": columns,
                "size_bytes": len(csv_data.encode('utf-8-sig'))
            }
        }
    except Exception as e:
        logger.exception("MXL to CSV conversion error")
        return {"status": "error", "error_message": str(e)}