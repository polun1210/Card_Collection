"""SQLite 連線與資料表建立。"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS card_mapping_candidate (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    series_raw           TEXT NOT NULL,
    number_raw           TEXT NOT NULL,
    card_name_raw        TEXT NOT NULL,
    series_normalized    TEXT NOT NULL,
    number_normalized    TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    confirmed_apparel_id INTEGER,
    UNIQUE (series_raw, number_raw, card_name_raw)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()
