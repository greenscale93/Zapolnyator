"""
Чтение данных из шаблона Excel-отчёта.

Извлечено из main.py для уменьшения размера модуля.
"""
import logging
import os
import tempfile
import zipfile
import openpyxl
import msoffcrypto

logger = logging.getLogger(__name__)


def get_template_offices(template_path: str) -> list:
    """
    Читает шаблон Excel и возвращает отсортированный список названий
    офисов/подразделений из листа 'Отчетность БИТ 2026'.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template file not found: {template_path}")

    wb = None
    try:
        # Сначала обычное открытие
        wb = openpyxl.load_workbook(template_path, data_only=True)
    except zipfile.BadZipFile:
        # Возможно файл зашифрован, пробуем расшифровать паролем "987456"
        try:
            with open(template_path, 'rb') as f:
                file = msoffcrypto.OfficeFile(f)
                if file.is_encrypted():
                    file.load_key(password="987456")
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                        file.decrypt(tmp)
                        tmp_path = tmp.name
                    wb = openpyxl.load_workbook(tmp_path, data_only=True)
                    os.unlink(tmp_path)
                else:
                    raise
        except Exception:
            raise ValueError(
                "Не удалось прочитать шаблон (возможно, повреждён или неверный пароль)"
            )

    if wb is None:
        raise ValueError("Не удалось открыть файл шаблона")

    if "Отчетность БИТ 2026" not in wb.sheetnames:
        wb.close()
        raise ValueError(
            "Лист 'Отчетность БИТ 2026' не найден в шаблоне"
        )

    ws = wb["Отчетность БИТ 2026"]
    offices = set()
    for row in range(16, 33):
        val = ws.cell(row=row, column=3).value
        if val and str(val).strip():
            offices.add(str(val).strip())
    for row in range(34, 36):
        val = ws.cell(row=row, column=3).value
        if val and str(val).strip():
            offices.add(str(val).strip())
    wb.close()
    return sorted(list(offices))
