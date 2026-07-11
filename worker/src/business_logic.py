"""
Backward-compatibility re-export.
All business logic has been moved to the `business_logic` package.
"""
import logging
from typing import List, Dict, Any, Optional

from src.business_logic.process_data import process_data as _process_data
from src.business_logic.filtering import EXCLUDED_DEPARTMENT, VGO_KEYWORDS, SCENARIO_FAKT

logger = logging.getLogger(__name__)

VALID_TYPES = ["Реализация", "Оплата", "Взаиморасчет", "НачислениеЗарплаты", "ФактическийФОТ"]


async def process_data(
    mxl_data: List[Dict[str, str]],
    month: str,
    year: int,
    rules: Dict[str, Any],
    user_mapping: Optional[Dict[str, str]] = None
) -> dict:
    """Делегирует реализацию в пакет business_logic."""
    return await _process_data(mxl_data, month, year, rules, user_mapping)