"""
Пакет обработчиков Telegram.

Разбит на модули для удобства поддержки:
- commands.py — команды /start, /reset, /autotest, /stop, /edit_mapping
- documents.py — загрузка и сохранение документов
- polling.py — мониторинг статуса задачи
- callbacks.py — inline-кнопки
- fsm.py — состояния FSM и обработка ответов
"""
from aiogram import Dispatcher
from . import commands, documents, polling, callbacks, fsm

__all__ = ["register_handlers"]


def register_handlers(dp: Dispatcher):
    """Регистрирует все роутеры из пакета handlers."""
    # Импортируем router из каждого модуля и подключаем к диспетчеру
    dp.include_router(commands.router)
    dp.include_router(documents.router)
    dp.include_router(polling.router)
    dp.include_router(callbacks.router)
    dp.include_router(fsm.router)
