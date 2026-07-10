import csv
import os
import logging
import chardet

logger = logging.getLogger(__name__)

async def parse_mxl(file_path: str) -> dict:
    """
    Парсит MXL-файл, автоматически определяет кодировку и разделитель.
    Поддерживает: табуляция, точка с запятой, запятая, вертикальная черта.
    """
    if not os.path.exists(file_path):
        return {"status": "error", "error_message": f"File not found: {file_path}"}
    
    try:
        # 1. Определяем кодировку
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)
            encoding = chardet.detect(raw_data)['encoding'] or 'utf-8'
        logger.info(f"Detected encoding: {encoding}")
        
        # 2. Читаем образец для определения разделителя
        with open(file_path, 'r', encoding=encoding, errors='replace') as f:
            sample = f.read(4096)
        
        # 3. Пробуем разделители
        possible_delimiters = ['\t', ';', ',', '|']
        delimiter = None
        for delim in possible_delimiters:
            if delim in sample:
                # Проверяем, что разделитель встречается примерно одинаково в строках
                lines = sample.splitlines()
                if len(lines) > 1:
                    counts = [line.count(delim) for line in lines[:5]]
                    if all(c > 0 for c in counts) and len(set(counts)) <= 1:
                        delimiter = delim
                        break
        if delimiter is None:
            # Если не удалось, выбираем самый частый
            delim_counts = {d: sample.count(d) for d in possible_delimiters}
            if max(delim_counts.values()) > 0:
                delimiter = max(delim_counts, key=delim_counts.get)
            else:
                return {"status": "error", "error_message": "Cannot detect delimiter in MXL file"}
        
        logger.info(f"Detected delimiter: {repr(delimiter)}")
        
        # 4. Читаем файл с определённым разделителем
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