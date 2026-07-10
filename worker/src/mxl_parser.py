import csv
import os
import logging
import chardet
import json
from io import StringIO

logger = logging.getLogger(__name__)

async def parse_mxl(file_path: str) -> dict:
    """
    Парсит MXL-файл (структурированный формат 1С) и возвращает данные в формате JSON.
    """
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        
        # 1. Извлечь колонки
        columns = []
        # Ищем блок с описанием колонок: {16,1, ...}
        # Внутри этого блока идут пары {1,1, {"#","ИмяКолонки"}}
        # Используем регулярное выражение для поиска всех вхождений {"#","..."}
        import json
        # Ищем блок {16,1,...} – проще найти все вхождения {16,1, и затем найти закрывающую }
        # Но проще использовать re.finditer для поиска {"#","..."} в пределах блока
        # Найдем все строки вида {"#","..."} – они могут быть внутри колонок
        column_matches = re.finditer(r'\{"#","([^"]*)"\}', content)
        for match in column_matches:
            col_name = match.group(1)
            if col_name and col_name not in columns:
                columns.append(col_name)
        # В примере колонки: ТипЗаписи, Дата, Номер, ... - они есть в списке
        # Но мы хотим сохранить порядок, поэтому лучше извлечь их последовательно из блока
        # Однако, re.finditer даст все в порядке появления – что в примере соответствует порядку колонок
        
        logger.info(f"Extracted columns: {columns}")
        if not columns:
            return {"status": "error", "error_message": "No columns found in MXL file"}
        
        # 2. Извлечение строк данных
        # Каждая строка данных начинается с {16,2, ...} или {16,3, ...}?
        # В примере каждая запись начинается с {16,2, {1,1, {"#","ТипЗаписи"}}, ...}
        # Затем идут значения, каждое в {16,3, ...} или {16,4, ...}
        # Мы можем извлечь все блоки {16,2, ...} и для каждого извлечь значения
        
        # Сначала найдём все блоки {16,2, ...} – они соответствуют записям
        # Используем парсер скобок – найдём все блоки, начинающиеся с {16,2,
        # Для этого будем использовать стек
        
        def parse_block(s, start):
            """Возвращает содержимое блока от позиции start до закрывающей скобки"""
            stack = []
            i = start
            while i < len(s):
                ch = s[i]
                if ch == '{':
                    stack.append(ch)
                elif ch == '}':
                    stack.pop()
                    if not stack:
                        return s[start:i+1]
                i += 1
            return None
        
        # Найдём все вхождения "{16,2," и извлечём блок
        records = []
        pos = 0
        while True:
            pos = content.find('{16,2,', pos)
            if pos == -1:
                break
            block = parse_block(content, pos)
            if block:
                records.append(block)
                pos += len(block)
            else:
                pos += 1
        
        logger.info(f"Found {len(records)} records")
        
        # 3. Для каждой записи извлечь значения
        data_rows = []
        for rec in records:
            # Извлекаем все значения из блоков {16,3, ...} и {16,4, ...}
            # Каждое значение может быть строкой или числом
            # Ищем внутри rec все вхождения {16,3, ...} и {16,4, ...} и извлекаем содержимое
            # Содержимое обычно в виде {1,1, {"#","значение"}} или {1,1, {"#","значение"}}
            # Или может быть {1,0} для пустого значения
            row_data = {}
            # Ищем все блоки {16,3, ...} и {16,4, ...}
            # Для каждого найдём значение
            # Мы можем извлечь все пары "ключ: значение"? Но проще пройти по записи и собрать все значения в порядке колонок
            # Поскольку каждая запись имеет значения в том же порядке, что и колонки, мы можем собрать их в список
            values = []
            # Используем re.finditer для поиска {16,3, ...} и {16,4, ...}
            # И извлекаем текст между {"#"," и "}
            # Или ищем {"#","..."}
            value_matches = re.finditer(r'\{"#","([^"]*)"\}', rec)
            for match in value_matches:
                val = match.group(1)
                # Некоторые значения могут быть числами с запятой, но они тоже в кавычках
                # Оставляем как есть
                values.append(val)
            # Также могут быть числовые значения без кавычек? В примере числа в кавычках.
            # Если в записи меньше значений, чем колонок, дополним пустыми
            if len(values) > len(columns):
                values = values[:len(columns)]
            elif len(values) < len(columns):
                values.extend([''] * (len(columns) - len(values)))
            # Сопоставляем с колонками
            row_dict = dict(zip(columns, values))
            data_rows.append(row_dict)
        
        logger.info(f"Parsed {len(data_rows)} rows")
        
        return {
            "status": "success",
            "result": {
                "data": data_rows,
                "columns": columns
            }
        }
    except Exception as e:
        logger.exception("MXL parsing error")
        return {"status": "error", "error_message": str(e)}
    
async def convert_mxl_to_csv(file_path: str) -> dict:
    """
    Парсит MXL и возвращает CSV-строку, а также сохраняет CSV-файл рядом с исходным.
    """
    if not os.path.exists(file_path):
        return {"status": "error", "error_message": f"File not found: {file_path}"}
    
    try:
        # Определяем кодировку
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)
            encoding = chardet.detect(raw_data)['encoding'] or 'utf-8'
        logger.info(f"Detected encoding: {encoding}")
        
        # Читаем образец для разделителя
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
        
        # Читаем все данные
        with open(file_path, 'r', encoding=encoding, errors='replace') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            data = list(reader)
            columns = reader.fieldnames if reader.fieldnames else []
        
        # Генерируем CSV-строку с тем же разделителем (табуляция или запятая?)
        # Для лучшей совместимости используем запятую
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=columns, delimiter=',')
        writer.writeheader()
        writer.writerows(data)
        csv_data = output.getvalue()
        
        # Сохраняем CSV-файл
        csv_path = file_path + ".csv"
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write(csv_data)
        
        return {
            "status": "success",
            "result": {
                "csv_data": csv_data,
                "csv_path": csv_path,
                "rows": len(data),
                "columns": columns
            }
        }
    except Exception as e:
        logger.exception("MXL to CSV conversion error")
        return {"status": "error", "error_message": str(e)}