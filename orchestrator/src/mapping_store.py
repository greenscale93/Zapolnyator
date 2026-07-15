import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app/data/rules.db")
DB_PATH = DATABASE_URL.replace("sqlite:///", "")


def _get_conn() -> sqlite3.Connection:
    """Создаёт соединение с БД, гарантируя существование директории."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"Created DB directory: {db_dir}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицу маппингов, если её нет. Безопасно вызывать многократно."""
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vz_office_mapping (
                contractor_office TEXT PRIMARY KEY,
                report_office TEXT NOT NULL
            )
        """)
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM vz_office_mapping").fetchone()[0]
        logger.info(f"Mapping DB initialized at {DB_PATH}, existing mappings: {count}")
    finally:
        conn.close()


def get_mapping_dict() -> dict:
    """Возвращает словарь {contractor_office: report_office} со всеми сохранёнными маппингами."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT contractor_office, report_office FROM vz_office_mapping"
        ).fetchall()
        result = {row["contractor_office"]: row["report_office"] for row in rows}
        if result:
            logger.info(f"Loaded {len(result)} saved mappings from DB")
        return result
    finally:
        conn.close()


def set_mapping(contractor_office: str, report_office: str):
    """Сохраняет или обновляет маппинг контрагента на подразделение отчёта."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO vz_office_mapping (contractor_office, report_office) "
            "VALUES (?, ?)",
            (contractor_office, report_office)
        )
        conn.commit()
        logger.info(f"Saved mapping: {contractor_office} -> {report_office}")
    finally:
        conn.close()


def delete_mapping(contractor_office: str):
    """Удаляет маппинг для указанного контрагента."""
    conn = _get_conn()
    try:
        conn.execute(
            "DELETE FROM vz_office_mapping WHERE contractor_office = ?",
            (contractor_office,)
        )
        conn.commit()
        logger.info(f"Deleted mapping for {contractor_office}")
    finally:
        conn.close()


def get_all_mappings() -> list:
    """Возвращает список кортежей (contractor_office, report_office)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT contractor_office, report_office FROM vz_office_mapping "
            "ORDER BY contractor_office"
        ).fetchall()
        return [(row["contractor_office"], row["report_office"]) for row in rows]
    finally:
        conn.close()


def get_mapping_count() -> int:
    """Возвращает количество сохранённых маппингов."""
    conn = _get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM vz_office_mapping").fetchone()[0]
    finally:
        conn.close()