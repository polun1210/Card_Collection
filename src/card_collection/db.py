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

CREATE TABLE IF NOT EXISTS card_candidate (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    mapping_candidate_id INTEGER NOT NULL REFERENCES card_mapping_candidate(id),
    apparel_id           INTEGER NOT NULL,
    name_en              TEXT NOT NULL,
    name_ja              TEXT NOT NULL,
    card_code            TEXT NOT NULL,
    image_url            TEXT NOT NULL,
    UNIQUE (mapping_candidate_id, apparel_id)
);

CREATE TABLE IF NOT EXISTS card (
    apparel_id           INTEGER PRIMARY KEY,
    product_catalog_id   INTEGER NOT NULL,
    name_en              TEXT NOT NULL,
    name_ja              TEXT NOT NULL,
    card_code            TEXT NOT NULL,
    image_url            TEXT NOT NULL,
    series_raw           TEXT NOT NULL,
    number_raw           TEXT NOT NULL,
    card_name_raw        TEXT NOT NULL,
    mapping_candidate_id INTEGER NOT NULL UNIQUE
                         REFERENCES card_mapping_candidate(id),
    confirmed_at         TEXT NOT NULL,
    image_local_path     TEXT
);

-- 持有品掛在卡種列上，不掛在已確認的卡種主檔上：推翻確認會刪掉主檔那一列，
-- 但你手上的實體卡不會因此消失。
CREATE TABLE IF NOT EXISTS holding (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    mapping_candidate_id INTEGER NOT NULL REFERENCES card_mapping_candidate(id),
    purchase_date        TEXT NOT NULL,
    purchase_date_raw    TEXT NOT NULL,
    cost_twd             INTEGER NOT NULL,
    sold_date            TEXT,
    sold_date_raw        TEXT,
    sold_price_twd       INTEGER,
    grading_raw          TEXT NOT NULL,
    source_row_number    INTEGER,
    created_at           TEXT NOT NULL
);

-- 匯入帳本：只要有一筆完成紀錄就不再匯入。CSV 是一次性的歷史補登入口，
-- 之後的真實來源是 CRUD——每次啟動重新對齊 CSV 會讓刪掉的持有品復活。
CREATE TABLE IF NOT EXISTS holding_import (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path          TEXT NOT NULL,
    source_fingerprint   TEXT NOT NULL,
    row_count            INTEGER NOT NULL,
    imported_at          TEXT NOT NULL
);
"""

# 尚未引入 Alembic（見 #1 規格）。在那之前，缺欄位就補上——只加不改。
_ADDED_COLUMNS = (
    ("card_mapping_candidate", "candidates_fetched_at", "TEXT"),
    ("card", "image_local_path", "TEXT"),
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    for table, column, column_type in _ADDED_COLUMNS:
        _add_column_if_missing(connection, table, column, column_type)
    connection.commit()


def _add_column_if_missing(
    connection: sqlite3.Connection, table: str, column: str, column_type: str
) -> None:
    existing = {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
