"""
Backward-compatibility re-export.
Все обработчики перенесены в пакет `handlers/`.
"""
import logging

from src.handlers import register_handlers as _register_handlers

logger = logging.getLogger(__name__)


def register_handlers(dp):
    """Делегирует регистрацию в пакет handlers."""
    _register_handlers(dp)