"""Восстановление pivot-таблиц и другие файловые утилиты."""
import zipfile
import os
import logging
import shutil

logger = logging.getLogger(__name__)


def restore_pivot_xml(original_template: str, output_path: str) -> None:
    """
    Копирует pivot-таблицы и pivot-кэши из оригинального шаблона в выходной xlsx.
    openpyxl не поддерживает pivot-таблицы — они теряются при wb.save().
    Эта функция восстанавливает их из чистого шаблона.

    Копирует:
    - xl/pivotTables/ (все файлы)
    - xl/pivotCache/ (все файлы)
    - Обновляет xl/workbook.xml (элемент <pivotCaches>)
    """
    if not os.path.exists(original_template):
        logger.warning(f"Template not found, skipping pivot restore: {original_template}")
        return
    if not os.path.exists(output_path):
        logger.warning(f"Output not found, skipping pivot restore: {output_path}")
        return

    tmp_path = output_path + ".tmp"
    try:
        with (
            zipfile.ZipFile(original_template, 'r') as zin,
            zipfile.ZipFile(output_path, 'r') as zout,
            zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as ztmp
        ):
            # Множества для отслеживания скопированных pivot-путей
            pivot_prefixes = ('xl/pivotTables/', 'xl/pivotCache/')

            # 1. Копируем pivot-файлы из оригинала
            for name in zin.namelist():
                if any(name.startswith(p) for p in pivot_prefixes):
                    data = zin.read(name)
                    ztmp.writestr(name, data)
                    logger.debug(f"Restored pivot file: {name}")

            # 2. Копируем xl/workbook.xml из оригинала (с правильными pivot-ссылками)
            #    Если в оригинале есть pivotCaches — используем его, иначе — из вывода
            if 'xl/workbook.xml' in zin.namelist():
                wb_xml = zin.read('xl/workbook.xml')
                ztmp.writestr('xl/workbook.xml', wb_xml)
                logger.debug("Restored xl/workbook.xml from original")
            elif 'xl/workbook.xml' in zout.namelist():
                wb_xml = zout.read('xl/workbook.xml')
                ztmp.writestr('xl/workbook.xml', wb_xml)

            # 3. Копируем все остальные файлы из вывода (с данными)
            for name in zout.namelist():
                if any(name.startswith(p) for p in pivot_prefixes):
                    continue  # уже скопированы из оригинала
                if name == 'xl/workbook.xml':
                    continue  # уже скопирован из оригинала (или будет скопирован ниже)
                data = zout.read(name)
                ztmp.writestr(name, data)

        # Замена
        shutil.move(tmp_path, output_path)
        logger.info(f"Pivot tables restored from template to {output_path}")

    except Exception as e:
        logger.error(f"Failed to restore pivot XML: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass