import csv
import os
import logging

logger = logging.getLogger(__name__)

async def parse_mxl(file_path: str) -> dict:
    """
    Парсит MXL-файл (TSV) и возвращает данные в формате JSON.
    """
    if not os.path.exists(file_path):
        return {"status": "error", "error_message": f"File not found: {file_path}"}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Определяем разделитель: табуляция или точка с запятой
            sample = f.read(1024)
            f.seek(0)
            if '\t' in sample:
                delimiter = '\t'
            elif ';' in sample:
                delimiter = ';'
            else:
                delimiter = None
            
            if delimiter is None:
                return {"status": "error", "error_message": "Cannot detect delimiter in MXL file"}
            
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