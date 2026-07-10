import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app/data/rules.db")
DB_PATH = DATABASE_URL.replace("sqlite:///", "")

def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vz_office_mapping (
            contractor_office TEXT PRIMARY KEY,
            report_office TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Mapping DB initialized")

def get_mapping_dict() -> dict:
    """Возвращает словарь {contractor_office: report_office}"""
    conn = _get_conn()
    rows = conn.execute("SELECT contractor_office, report_office FROM vz_office_mapping").fetchall()
    conn.close()
    return {row["contractor_office"]: row["report_office"] for row in rows}

def set_mapping(contractor_office: str, report_office: str):
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO vz_office_mapping (contractor_office, report_office) VALUES (?, ?)",
        (contractor_office, report_office)
    )
    conn.commit()
    conn.close()
    logger.info(f"Saved mapping: {contractor_office} -> {report_office}")

def delete_mapping(contractor_office: str):
    conn = _get_conn()
    conn.execute("DELETE FROM vz_office_mapping WHERE contractor_office = ?", (contractor_office,))
    conn.commit()
    conn.close()
    logger.info(f"Deleted mapping for {contractor_office}")

def get_all_mappings() -> list:
    """Возвращает список (contractor_office, report_office)"""
    conn = _get_conn()
    rows = conn.execute("SELECT contractor_office, report_office FROM vz_office_mapping").fetchall()
    conn.close()
    return [(row["contractor_office"], row["report_office"]) for row in rows]