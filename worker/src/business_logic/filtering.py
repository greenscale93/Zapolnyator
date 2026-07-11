import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

EXCLUDED_DEPARTMENT = "ГКП 10.6 (Емельянова)"
VGO_KEYWORDS = ["ВГО", "вго", "внутригрупповые"]
SCENARIO_FAKT = "ФАКТ"


async def filter_rows(
    mxl_data: List[Dict[str, str]],
    columns: dict,
    month: str,
    year: int
) -> dict:
    """
    Фильтрует данные:
    - Оставляет только сценарий ФАКТ
    - Исключает подразделение 'ГКП 10.6 (Емельянова)'
    - Исключает ВГО-строки
    Возвращает dict с filtered_rows или clarification при пустом результате.
    """
    col_scenario = columns.get("scenario")
    col_department = columns.get("department")
    col_vgo = columns.get("vgo")
    col_direction = columns.get("direction")

    filtered_rows = []
    for row in mxl_data:
        scenario = row.get(col_scenario, "").strip()
        department = row.get(col_department, "").strip()
        vgo_value = row.get(col_vgo, "").strip() if col_vgo else ""
        direction = row.get(col_direction, "").strip() if col_direction else ""

        if scenario.upper() != SCENARIO_FAKT:
            continue
        if EXCLUDED_DEPARTMENT in department:
            continue
        if vgo_value.lower() == "да" or any(kw in direction.lower() for kw in VGO_KEYWORDS):
            continue
        filtered_rows.append(row)

    if not filtered_rows:
        col_type = columns.get("type")
        sample_rows = mxl_data[:5] if mxl_data else []
        sample_info = []
        for row in sample_rows:
            sample_info.append({
                "type": row.get(col_type, ""),
                "scenario": row.get(col_scenario, ""),
                "department": row.get(col_department, "")
            })
        return {
            "status": "needs_clarification",
            "clarification": {
                "question": (
                    f"После фильтрации не осталось данных. Проверьте, что в выгрузке "
                    f"есть записи со сценарием '{SCENARIO_FAKT}' и они не относятся "
                    f"к '{EXCLUDED_DEPARTMENT}'. Образцы: {sample_info}"
                ),
                "context": {
                    "type": "filtering_issue",
                    "sample_rows": sample_info,
                    "columns": list(mxl_data[0].keys()) if mxl_data else []
                }
            }
        }

    return {"status": "ok", "filtered_rows": filtered_rows}
