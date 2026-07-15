import sqlite3
import os
import json
import logging
from typing import Optional, Any, Dict, List

logger = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, db_path: str | None = None):
        # По умолчанию используем тот же путь, что и mapping_store
        self.db_path = db_path or os.getenv(
            "DATABASE_URL", "sqlite:///app/data/rules.db"
        ).replace("sqlite:///", "")
        self._init_db()

    def _init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS subdivision_rules (
                id INTEGER PRIMARY KEY,
                key TEXT UNIQUE,
                type TEXT,
                turnover_type TEXT,
                comment_prefix BOOLEAN,
                comment_text TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS employee_exceptions (
                id INTEGER PRIMARY KEY,
                employee_name TEXT UNIQUE,
                exclude_from_ffot BOOLEAN,
                exclude_types TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS vat_exceptions (
                id INTEGER PRIMARY KEY,
                vat_rate TEXT UNIQUE,
                mapped TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def _get_conn(self):
        """Возвращает новое соединение с БД."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def save_rule(self, context: dict, answer: str):
        """
        Сохраняет правило на основе контекста и ответа пользователя.

        Определяет тип сохраняемого правила по context['type']:
        - 'subdivision' → subdivision_rules
        - 'employee' → employee_exceptions
        - 'vat' → vat_exceptions
        """
        rule_type = context.get("type", "subdivision")
        conn = self._get_conn()
        try:
            if rule_type == "subdivision":
                conn.execute(
                    """INSERT OR REPLACE INTO subdivision_rules
                       (key, type, turnover_type, comment_prefix, comment_text)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        context.get("key", ""),
                        context.get("subdivision_type", "internal"),
                        context.get("turnover_type"),
                        context.get("comment_prefix", False),
                        answer
                    )
                )
            elif rule_type == "employee":
                conn.execute(
                    """INSERT OR REPLACE INTO employee_exceptions
                       (employee_name, exclude_from_ffot, exclude_types)
                       VALUES (?, ?, ?)""",
                    (
                        context.get("employee_name", ""),
                        context.get("exclude_from_ffot", False),
                        json.dumps(context.get("exclude_types", []), ensure_ascii=False)
                    )
                )
            elif rule_type == "vat":
                conn.execute(
                    """INSERT OR REPLACE INTO vat_exceptions
                       (vat_rate, mapped) VALUES (?, ?)""",
                    (context.get("vat_rate", ""), answer)
                )
            conn.commit()
            logger.info(f"Saved rule: type={rule_type}, context={context}")
        finally:
            conn.close()

    async def get_rule(self, key: str, rule_type: str = "subdivision") -> Optional[Any]:
        """
        Получает правило по ключу и типу.
        Возвращает словарь с данными правила или None.
        """
        conn = self._get_conn()
        try:
            if rule_type == "subdivision":
                row = conn.execute(
                    "SELECT * FROM subdivision_rules WHERE key = ?", (key,)
                ).fetchone()
            elif rule_type == "employee":
                row = conn.execute(
                    "SELECT * FROM employee_exceptions WHERE employee_name = ?", (key,)
                ).fetchone()
            elif rule_type == "vat":
                row = conn.execute(
                    "SELECT * FROM vat_exceptions WHERE vat_rate = ?", (key,)
                ).fetchone()
            else:
                return None

            if row:
                return dict(row)
            return None
        finally:
            conn.close()

    def get_db_path(self) -> str:
        """Возвращает путь к файлу БД."""
        return self.db_path

    async def load_all_rules(self) -> Dict[str, Any]:
        """
        Загружает все правила из БД.
        Возвращает словарь с разделами:
        {
            "subdivision_rules": [...],
            "employee_exceptions": [...],
            "vat_exceptions": [...]
        }
        """
        conn = self._get_conn()
        try:
            subdivisions = [
                dict(row) for row in conn.execute(
                    "SELECT * FROM subdivision_rules"
                ).fetchall()
            ]
            employees = [
                dict(row) for row in conn.execute(
                    "SELECT * FROM employee_exceptions"
                ).fetchall()
            ]
            vat = [
                dict(row) for row in conn.execute(
                    "SELECT * FROM vat_exceptions"
                ).fetchall()
            ]
            logger.info(
                f"Loaded rules: {len(subdivisions)} subdivisions, "
                f"{len(employees)} employees, {len(vat)} VAT"
            )
            return {
                "subdivision_rules": subdivisions,
                "employee_exceptions": employees,
                "vat_exceptions": vat
            }
        finally:
            conn.close()

    async def save_column_mapping(self, mapping: Dict[str, str]) -> None:
        """Сохраняет маппинг колонок в отдельную таблицу."""
        conn = self._get_conn()
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS column_mappings (
                    id INTEGER PRIMARY KEY,
                    key TEXT,
                    value TEXT,
                    UNIQUE(key)
                )
            ''')
            for key, value in mapping.items():
                conn.execute(
                    'REPLACE INTO column_mappings (key, value) VALUES (?, ?)',
                    (key, value)
                )
            conn.commit()
        finally:
            conn.close()