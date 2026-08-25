"""待確認卡種的讀寫介面。業務邏輯只認這個介面，不認 SQL。"""

import sqlite3
from collections.abc import Iterable

from .notion_csv import CardKind

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"

_QUEUE_COLUMNS = (
    "id, series_raw, number_raw, card_name_raw, "
    "series_normalized, number_normalized, status"
)
_STABLE_ORDER = "ORDER BY series_normalized, number_normalized, card_name_raw"


class MappingCandidateRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def seed(self, kinds: Iterable[CardKind]) -> None:
        """匯入相異卡種。重複執行不會重複匯入，也不會覆寫既有狀態。"""
        self._connection.executemany(
            """
            INSERT INTO card_mapping_candidate
                (series_raw, number_raw, card_name_raw,
                 series_normalized, number_normalized, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            ON CONFLICT (series_raw, number_raw, card_name_raw) DO NOTHING
            """,
            [
                (
                    kind.series_raw,
                    kind.number_raw,
                    kind.card_name_raw,
                    kind.series_normalized,
                    kind.number_normalized,
                )
                for kind in kinds
            ],
        )
        self._connection.commit()

    def list_pending(self, limit: int | None = None) -> tuple[dict, ...]:
        query = (
            f"SELECT {_QUEUE_COLUMNS} FROM card_mapping_candidate "
            f"WHERE status = ? {_STABLE_ORDER}"
        )
        parameters: tuple = (STATUS_PENDING,)
        if limit is not None:
            query += " LIMIT ?"
            parameters += (limit,)
        rows = self._connection.execute(query, parameters).fetchall()
        return tuple(dict(row) for row in rows)

    def progress(self) -> dict[str, int]:
        counted = {
            row["status"]: row["total"]
            for row in self._connection.execute(
                "SELECT status, COUNT(*) AS total "
                "FROM card_mapping_candidate GROUP BY status"
            )
        }
        return {
            STATUS_CONFIRMED: counted.get(STATUS_CONFIRMED, 0),
            STATUS_REJECTED: counted.get(STATUS_REJECTED, 0),
            STATUS_PENDING: counted.get(STATUS_PENDING, 0),
        }
