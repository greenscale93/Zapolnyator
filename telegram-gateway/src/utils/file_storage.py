"""
Утилиты для работы с файлами: сохранение/загрузка последних файлов,
извлечение месяца и года из имени файла.
"""
import os
import json
import re
import logging

logger = logging.getLogger(__name__)

TEMP_DIR = os.getenv("TEMP_DIR", "/app/temp")
LAST_FILES_PATH = os.path.join(TEMP_DIR, "last_files.json")


def save_last_files(excel_path: str, data_path: str):
    """Сохраняет пути к последним файлам в JSON."""
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        with open(LAST_FILES_PATH, 'w') as f:
            json.dump({"excel": excel_path, "data": data_path}, f)
    except Exception as e:
        logger.warning(f"Could not save last files: {e}")


def get_last_files():
    """Возвращает (excel_path, data_path) из сохранённых последних файлов."""
    try:
        if os.path.exists(LAST_FILES_PATH):
            with open(LAST_FILES_PATH, 'r') as f:
                data = json.load(f)
            return data.get("excel"), data.get("data")
    except Exception:
        pass
    return None, None


def extract_month_year_from_filename(filename: str) -> tuple:
    """
    Извлекает месяц и год из имени файла вида 'ВыгрузкаДляExcel_2026_05...'.
    Возвращает (month_name, year). По умолчанию ('Май', 2026).
    """
    pattern = r'ВыгрузкаДляExcel[_\-]?(\d{4})[-_](\d{2})'
    match = re.search(pattern, filename)
    if match:
        year = int(match.group(1))
        month_num = int(match.group(2))
        months_ru = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }
        month_name = months_ru.get(month_num, "Май")
        return month_name, year
    return "Май", 2026
