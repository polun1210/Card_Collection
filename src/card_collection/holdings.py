"""持有品的讀寫介面與衍生數字。業務邏輯只認這個介面，不認 SQL。"""

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from .notion_csv import HoldingRow

STATUS_HELD = "held"
STATUS_SOLD = "sold"

_SELECT_HOLDINGS = """
SELECT holding.id,
       holding.mapping_candidate_id,
       card.apparel_id,
       kind.series_raw,
       kind.number_raw,
       kind.card_name_raw,
       holding.purchase_date,
       holding.purchase_date_raw,
       holding.cost_twd,
       holding.sold_date,
       holding.sold_date_raw,
       holding.sold_price_twd,
       holding.grading_raw,
       holding.source_row_number
FROM holding
JOIN card_mapping_candidate AS kind ON kind.id = holding.mapping_candidate_id
LEFT JOIN card ON card.mapping_candidate_id = kind.id
"""
_STABLE_ORDER = (
    "ORDER BY kind.series_normalized, kind.number_normalized, kind.card_name_raw, "
    "holding.purchase_date, holding.id"
)


def summarize(holdings: Sequence[dict]) -> dict[str, int]:
    """持有成本只算持有中的；已實現損益只算已售出的。兩者永不混入同一個數字。"""
    held = [holding for holding in holdings if holding["status"] == STATUS_HELD]
    sold = [holding for holding in holdings if holding["status"] == STATUS_SOLD]
    return {
        "held_count": len(held),
        "sold_count": len(sold),
        "held_cost_twd": sum(holding["cost_twd"] for holding in held),
        "realized_pnl_twd": sum(holding["realized_pnl_twd"] for holding in sold),
    }


def _to_holding(row: sqlite3.Row) -> dict:
    """已售出才帶損益欄位。持有中的損益需要市值，市值還不存在。

    缺的數字就讓欄位不存在，不是 null 也不是 0——0 會被讀成「不賺不賠」。
    """
    holding = dict(row)
    if holding["sold_date"] is None:
        return {**holding, "status": STATUS_HELD}
    realized = holding["sold_price_twd"] - holding["cost_twd"]
    return {
        **holding,
        "status": STATUS_SOLD,
        "realized_pnl_twd": realized,
        "return_rate": realized / holding["cost_twd"],
    }


class HoldingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def has_completed_import(self) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM holding_import LIMIT 1"
        ).fetchone()
        return row is not None

    def import_batch(
        self,
        rows: Iterable[tuple[int, HoldingRow]],
        source_path: str,
        source_fingerprint: str,
    ) -> None:
        """整批與帳本同一個交易。任何一列失敗就整批不留，不生半成品。"""
        now = datetime.now(UTC).isoformat()
        values = [
            (
                mapping_candidate_id,
                row.purchase_date,
                row.purchase_date_raw,
                row.cost_twd,
                row.sold_date,
                row.sold_date_raw,
                row.sold_price_twd,
                row.grading_raw,
                row.source_row_number,
                now,
            )
            for mapping_candidate_id, row in rows
        ]
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO holding
                    (mapping_candidate_id, purchase_date, purchase_date_raw, cost_twd,
                     sold_date, sold_date_raw, sold_price_twd, grading_raw,
                     source_row_number, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self._connection.execute(
                "INSERT INTO holding_import "
                "(source_path, source_fingerprint, row_count, imported_at) "
                "VALUES (?, ?, ?, ?)",
                (source_path, source_fingerprint, len(values), now),
            )

    def list_all(self) -> tuple[dict, ...]:
        rows = self._connection.execute(f"{_SELECT_HOLDINGS} {_STABLE_ORDER}")
        return tuple(_to_holding(row) for row in rows)

    def list_for_apparel(self, apparel_id: int) -> tuple[dict, ...]:
        rows = self._connection.execute(
            f"{_SELECT_HOLDINGS} WHERE card.apparel_id = ? {_STABLE_ORDER}",
            (apparel_id,),
        )
        return tuple(_to_holding(row) for row in rows)

    def list_imports(self) -> tuple[dict, ...]:
        rows = self._connection.execute(
            "SELECT source_path, source_fingerprint, row_count, imported_at "
            "FROM holding_import ORDER BY id"
        )
        return tuple(dict(row) for row in rows)
