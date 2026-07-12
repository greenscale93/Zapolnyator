"""Восстановление pivot-таблиц и другие файловые утилиты."""
import zipfile
import os
import logging
import shutil

logger = logging.getLogger(__name__)


def restore_pivot_xml(original_template: str, output_path: str) -> None:
    """
    Копирует pivot-таблицы и pivot-кэши из оригинального шаблона в выходной xlsx.
    Поддерживает зашифрованные шаблоны (пароль 987456).
    """
    import tempfile

    if not os.path.exists(original_template):
        logger.warning(f"Template not found, skipping pivot restore: {original_template}")
        return
    if not os.path.exists(output_path):
        logger.warning(f"Output not found, skipping pivot restore: {output_path}")
        return

    # Расшифровываем оригинал, если зашифрован
    decrypted = original_template
    try:
        with zipfile.ZipFile(original_template, 'r') as test_zip:
            pass  # работает, не зашифрован
    except Exception:
        logger.info("Template is encrypted, decrypting for pivot restore...")
        try:
            import msoffcrypto
            with open(original_template, 'rb') as f:
                office = msoffcrypto.OfficeFile(f)
                if office.is_encrypted():
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                    tmp_name = tmp.name
                    tmp.close()
                    office.load_key(password="987456")
                    with open(tmp_name, 'wb') as fout:
                        office.decrypt(fout)
                    decrypted = tmp_name
                else:
                    logger.warning("File cannot be opened as zip and is not encrypted, skipping")
                    return
        except Exception as e:
            logger.error(f"Cannot decrypt template for pivot restore: {e}")
            return

    tmp_path = output_path + ".tmp"
    try:
        with (
            zipfile.ZipFile(decrypted, 'r') as zin,
            zipfile.ZipFile(output_path, 'r') as zout,
            zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as ztmp
        ):
            pivot_prefixes = ('xl/pivotTables/', 'xl/pivotCache/')
            for name in zin.namelist():
                if any(name.startswith(p) for p in pivot_prefixes):
                    data = zin.read(name)
                    ztmp.writestr(name, data)
                    logger.debug(f"Restored pivot file: {name}")
            if 'xl/workbook.xml' in zin.namelist():
                wb_xml = zin.read('xl/workbook.xml')
                ztmp.writestr('xl/workbook.xml', wb_xml)
                logger.debug("Restored xl/workbook.xml from original")
            elif 'xl/workbook.xml' in zout.namelist():
                wb_xml = zout.read('xl/workbook.xml')
                ztmp.writestr('xl/workbook.xml', wb_xml)
            for name in zout.namelist():
                if any(name.startswith(p) for p in pivot_prefixes):
                    continue
                if name == 'xl/workbook.xml':
                    continue
                data = zout.read(name)
                ztmp.writestr(name, data)
        shutil.move(tmp_path, output_path)
        logger.info(f"Pivot tables restored from template to {output_path}")
    except Exception as e:
        logger.error(f"Failed to restore pivot XML: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    finally:
        # Удаляем временный расшифрованный файл
        if decrypted != original_template and os.path.exists(decrypted):
            try:
                os.remove(decrypted)
            except Exception:
                pass