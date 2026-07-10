import sqlite3
import os
import json
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

class MemoryStore:
    def __init__(self, db_path: str = "/app/data/rules.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
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

    async def save_rule(self, context: dict, answer: str):
        # Здесь будет логика сохранения правила в зависимости от контекста
        # Пока заглушка
        logger.info(f"Сохранение правила: context={context}, answer={answer}")
        # В реальности парсить context и answer и вставлять в таблицу

    async def get_rule(self, key: str, rule_type: str) -> Optional[Any]:
        # Заглушка
        return None

    async def load_all_rules(self) -> Dict[str, Any]:
        """Загружает все правила из памяти."""
        # Здесь можно загрузить из таблиц subdivision_rules, employee_exceptions, vat_exceptions
        # Пока возвращаем пустой словарь
        return {}
    
    async def save_column_mapping(self, mapping: Dict[str, str]) -> None:
        """Сохраняет маппинг колонок в отдельную таблицу."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS column_mappings (
                id INTEGER PRIMARY KEY,
                key TEXT,
                value TEXT,
                UNIQUE(key)
            )
        ''')
        for key, value in mapping.items():
            c.execute('REPLACE INTO column_mappings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()