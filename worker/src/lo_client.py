"""
LibreOffice UNO API client.

Управляет соединением с фоновым soffice и предоставляет методы
для чтения/записи Excel-файлов без openpyxl.

Все операции потокобезопасны через asyncio Lock.
"""
import os
import logging
import asyncio
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

_uno = None
_uno_available = False

try:
    import uno
    from com.sun.star.beans import PropertyValue
    _uno_available = True
except ImportError:
    logger.warning("UNO not available — LibreOffice operations will fail")


class LoClient:
    """Обёртка над LibreOffice UNO API для операций с Excel."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._desktop = None
        self._connected = False
        if _uno_available:
            self._connect()

    def _connect(self):
        """Подключается к фоновому soffice."""
        try:
            local_context = uno.getComponentContext()
            resolver = local_context.ServiceManager.createInstanceWithContext(
                "com.sun.star.bridge.UnoUrlResolver", local_context
            )
            ctx = resolver.resolve(
                "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext"
            )
            self._desktop = ctx.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", ctx
            )
            self._connected = True
            logger.info("LibreOffice UNO connected")
        except Exception as e:
            logger.error(f"LibreOffice UNO connection failed: {e}")
            self._connected = False

    def _ensure_connected(self):
        if not _uno_available or not self._connected:
            raise RuntimeError("LibreOffice UNO not available")

    def _to_uno_url(self, path: str) -> str:
        """Конвертирует путь файла в UNO URL."""
        return uno.systemPathToFileUrl(os.path.abspath(path))

    async def open_document(self, path: str, password: str = None):
        """
        Открывает Excel-файл на запись через LibreOffice.
        При необходимости расшифровывает (msoffcrypto) и открывает decrypted копию.
        """
        async with self._lock:
            self._ensure_connected()

            # Если файл зашифрован — сначала расшифровываем через msoffcrypto
            file_path = path
            tmp = None
            if password:
                try:
                    import msoffcrypto
                    import tempfile
                    with open(path, 'rb') as f:
                        office_file = msoffcrypto.OfficeFile(f)
                        if office_file.is_encrypted():
                            office_file.load_key(password=password)
                            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                            office_file.decrypt(tmp)
                            tmp.close()
                            file_path = tmp.name
                            logger.info(f"Decrypted template: {file_path}")
                except Exception as e:
                    logger.warning(f"Decrypt failed (will try as-is): {e}")

            url = self._to_uno_url(file_path)
            doc = self._desktop.loadComponentFromURL(url, "_blank", 0, ())

            if tmp and file_path != path:
                try:
                    os.unlink(file_path)
                except Exception:
                    pass

            logger.info(f"Opened document: {path}")
            return doc

    async def get_sheet(self, doc, sheet_name: str):
        """Возвращает лист по имени."""
        sheets = doc.getSheets()
        if not sheets.hasByName(sheet_name):
            raise ValueError(f"Sheet '{sheet_name}' not found")
        return sheets.getByName(sheet_name)

    async def write_cell(self, sheet, col: int, row: int, value):
        """
        Записывает значение в ячейку (col, row — 0-based).
        Числа записываются как float, остальное — как строка.
        """
        async with self._lock:
            cell = sheet.getCellByPosition(col, row)
            if value is None:
                return
            if isinstance(value, (int, float)):
                cell.setValue(float(value))
            else:
                # Период и другие текстовые значения — как строка
                cell.setString(str(value))

    async def find_last_row(self, sheet, max_column: int = 30) -> int:
        """Находит последнюю использованную строку (0-based)."""
        async with self._lock:
            last = 0
            for row in range(1000):  # разумный лимит
                has_data = False
                for col in range(max_column):
                    cell = sheet.getCellByPosition(col, row)
                    if cell.getString() or cell.getValue() != 0.0:
                        has_data = True
                        break
                if has_data:
                    last = row
                elif last > 0 and row > last + 5:
                    break  # 5 пустых строк подряд — конец
            return last

    async def append_rows(
        self,
        sheet,
        data: List[Dict[int, Any]],
        start_row: Optional[int] = None,
        header_row: int = 1
    ):
        """
        Добавляет строки данных на лист.
        data — список словарей {col_idx: value} (0-based col_idx).
        Если start_row не указан — находит последнюю строку и добавляет после неё.
        """
        async with self._lock:
            if start_row is None:
                start_row = await self.find_last_row(sheet) + 1

            if start_row <= header_row:
                start_row = header_row + 1

            for i, row_data in enumerate(data):
                r = start_row + i
                for col_idx, value in row_data.items():
                    await self.write_cell(sheet, col_idx, r, value)

            logger.info(f"Appended {len(data)} rows starting at row {start_row}")
            return start_row

    async def save_document(self, doc, path: str):
        """Сохраняет документ в XLSX формате."""
        async with self._lock:
            props = (
                PropertyValue("FilterName", 0, "Calc MS Excel 2007 XML", 0),
            )
            url = self._to_uno_url(path)
            doc.storeToURL(url, props)
            logger.info(f"Saved: {path}")

    async def close_document(self, doc):
        """Закрывает документ без сохранения."""
        async with self._lock:
            try:
                doc.close(True)
            except Exception:
                pass

    async def close(self):
        """Закрывает соединение."""
        async with self._lock:
            if self._desktop:
                try:
                    self._desktop.terminate()
                except Exception:
                    pass
            self._connected = False


# Глобальный singleton
lo_client = LoClient() if _uno_available else None
