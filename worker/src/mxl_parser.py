import csv
import os
import logging
import re  # <-- добавили импорт
import chardet
from io import StringIO

logger = logging.getLogger(__name__)

async def parse_mxl(file_path: str) -> dict:
    """
    Парсит MXL-файл, автоматически определяет кодировку и разделитель.
    Поддерживает: табуляция, точка с запятой, запятая, вертикальная черта.
    """
    if not os.path.exists(file_path):
        return {"status": "error", "error_message": f"File not found: {file_path}"}
    
    try:
        # Определяем кодировку
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)
            encoding = chardet.detect(raw_data)['encoding'] or 'utf-8'
        logger.info(f"Detected encoding: {encoding}")
        
        # Читаем образец для определения разделителя
        with open(file_path, 'r', encoding=encoding, errors='replace') as f:
            sample = f.read(4096)
        
        possible_delimiters = ['\t', ';', ',', '|']
        delimiter = None
        for delim in possible_delimiters:
            if delim in sample:
                lines = sample.splitlines()
                if len(lines) > 1:
                    counts = [line.count(delim) for line in lines[:5]]
                    if all(c > 0 for c in counts) and len(set(counts)) <= 1:
                        delimiter = delim
                        break
        if delimiter is None:
            delim_counts = {d: sample.count(d) for d in possible_delimiters}
            if max(delim_counts.values()) > 0:
                delimiter = max(delim_counts, key=delim_counts.get)
            else:
                return {"status": "error", "error_message": "Cannot detect delimiter in MXL file"}
        
        logger.info(f"Detected delimiter: {repr(delimiter)}")
        
        # Читаем файл
        with open(file_path, 'r', encoding=encoding, errors='replace') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            data = list(reader)
            columns = reader.fieldnames if reader.fieldnames else []
        
        return {
            "status": "success",
            "result": {
                "data": data,
                "columns": columns
            }
        }
    except Exception as e:
        logger.exception("MXL parsing error")
        return {"status": "error", "error_message": str(e)}

async def convert_mxl_to_csv(file_path: str) -> dict:
    """
    Конвертирует MXL-файл в CSV и возвращает CSV-строку и путь к сохранённому CSV.
    """
    parsed = await parse_mxl(file_path)
    if parsed.get("status") == "error":
        return parsed
    
    data = parsed["result"]["data"]
    columns = parsed["result"]["columns"]
    
    if not data:
        return {"status": "error", "error_message": "No data found in MXL"}
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, delimiter=',', quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    # Удаляем непечатаемые символы из значений
    cleaned_data = []
    for row in data:
        cleaned_row = {}
        for k, v in row.items():
            if isinstance(v, str):
                # Удаляем управляющие символы, но сохраняем переносы строк
                v = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', v)
            cleaned_row[k] = v
        cleaned_data.append(cleaned_row)
    writer.writerows(cleaned_data)
    csv_data = output.getvalue()
    
    # Сохраняем CSV рядом с исходным файлом
    csv_path = file_path + ".csv"
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write(csv_data)
    
    logger.info(f"Converted MXL to CSV: {csv_path} ({len(csv_data)} chars, {len(data)} rows)")
    
    return {
        "status": "success",
        "result": {
            "csv_data": csv_data,
            "csv_path": csv_path,
            "rows": len(data),
            "columns": columns,
            "size_chars": len(csv_data)
        }
    }