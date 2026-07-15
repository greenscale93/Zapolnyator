---
description: "Use when writing or reviewing Python code in the Zapolnyator project. Covers type hints, async patterns, error handling, 1С data quirks, and project conventions."
applyTo: ["**/*.py"]
---

# Python Code Standards — Zapolnyator

## Type Hints (обязательно)
- Все функции: аннотации параметров + возврата (включая `-> None`)
- Python 3.10+: `str | None` вместо `Optional[str]`, `dict`/`list` вместо `Dict`/`List`
- Для сложных вложенных типов: `dict[str, Any]` из `typing`

## Async/await
- Код полностью асинхронный. Файлы — через `aiofiles`, HTTP — `httpx.AsyncClient`, Redis — `redis.asyncio`
- Если синхронная библиотека (openpyxl, pandas) — оставлять в `async def`, НО с комментарием, что вызов блокирующий

## Обработка ошибок
- Внутренние функции возвращают `{"status": "success"|"error", "result": ..., "error_message": ...}`
- FastAPI endpoints — `raise HTTPException(code, message)`
- Все `except` логируют ошибку: `logger.exception()` или `logger.warning()`
- Для AI-агента: статус `"needs_clarification"` — вопрос пользователю

## Данные из 1С
- В числах могут быть неразрывные пробелы (`\xa0`) — всегда очищать
- MXL-файлы могут быть запаролены → msoffcrypto-tool
- Кодировки → chardet

## openpyxl
- **НЕ использовать** `data_only=True` при записи — убивает формулы
- Для пересчёта формул использовать LibreOffice: `subprocess.run(["libreoffice", "--headless", "--calc", "--convert-to", "xlsx", path])`

## Чистота кода
- `print()` запрещён — только `logger.*`
- Импорты: stdlib → third-party → project (группы с пустыми строками)
- Модули >500 строк → выделять подпакет с реэкспортом в `__init__.py`
