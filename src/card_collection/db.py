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
-- 成交紀錄掛在已確認的卡種主檔上：行情是對應關係的衍生物，對應被推翻，
-- 依它抓來的行情就不該留著。
CREATE TABLE IF NOT EXISTS sale (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    apparel_id           INTEGER NOT NULL REFERENCES card(apparel_id),
    sold_at_raw          TEXT NOT NULL,
    sold_date_jst        TEXT NOT NULL,
    price_jpy            INTEGER NOT NULL,
    condition_raw        TEXT NOT NULL,
    variant_raw          TEXT NOT NULL,
    -- 完全相同的成交（同秒、同價、同枚数）確實存在，實測有一組五筆。
    -- 唯一鍵不含序號的話，五筆真實成交會被去重成一筆。
    duplicate_index      INTEGER NOT NULL,
    price_twd            INTEGER,
    fx_rate              REAL,
    fx_rate_date         TEXT,
    fx_source            TEXT,
    status               TEXT NOT NULL,
    quarantine_reason    TEXT,
    fetched_at           TEXT NOT NULL,
    UNIQUE (apparel_id, sold_at_raw, price_jpy, variant_raw, duplicate_index)
);

-- 匯率一經寫入即固定，永不以今日匯率回頭重算歷史（ADR-0006）。
-- 來源與實際牌告日一起存，日後換來源時分辨得出哪些數字來自哪裡。
CREATE TABLE IF NOT EXISTS fx_rate (
    rate_date            TEXT PRIMARY KEY,
    rate                 REAL NOT NULL,
    source               TEXT NOT NULL,
    fetched_at           TEXT NOT NULL
);

-- 抓取帳本：已經抓過的日期不重抓。來源是一份六個月的整包 CSV，
-- 所以「抓過到哪一天」就足以決定下一次要不要再打這個請求。
CREATE TABLE IF NOT EXISTS fx_fetch (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    requested_through    TEXT NOT NULL,
    source               TEXT NOT NULL,
    row_count            INTEGER NOT NULL,
    fetched_at           TEXT NOT NULL
);

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
