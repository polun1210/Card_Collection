"""待確認卡種的讀寫介面。業務邏輯只認這個介面，不認 SQL。"""

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime

from .notion_csv import CardKind
from .snkrdunk import Candidate

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"

_QUEUE_COLUMNS = (
    "id, series_raw, number_raw, card_name_raw, "
    "series_normalized, number_normalized, status, candidates_fetched_at"
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
        return tuple(
            self.with_candidates(row)
            for row in self._select_pending(_QUEUE_COLUMNS, limit)
        )

    def find_pending(self, mapping_candidate_id: int) -> dict | None:
        row = self._connection.execute(
            f"SELECT {_QUEUE_COLUMNS} FROM card_mapping_candidate "
            "WHERE id = ? AND status = ?",
            (mapping_candidate_id, STATUS_PENDING),
        ).fetchone()
        return dict(row) if row else None

    def with_candidates(self, row: dict) -> dict:
        return {**row, "candidates": self._candidates_of(row["id"])}

    def list_without_candidates(self, limit: int | None = None) -> tuple[dict, ...]:
        """尚未向 SNKRDUNK 查過候選的列。查過但查無結果的不再重查。"""
        return self._select_pending(
            _QUEUE_COLUMNS, limit, extra_where="AND candidates_fetched_at IS NULL"
        )

    def record_candidates(
        self, mapping_candidate_id: int, candidates: Iterable[Candidate]
    ) -> None:
        self._connection.executemany(
            """
            INSERT INTO card_candidate
                (mapping_candidate_id, apparel_id, name_en, name_ja, card_code, image_url)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (mapping_candidate_id, apparel_id) DO NOTHING
            """,
            [
                (
                    mapping_candidate_id,
                    candidate.apparel_id,
                    candidate.name_en,
                    candidate.name_ja,
                    candidate.card_code,
                    candidate.image_url,
                )
                for candidate in candidates
            ],
        )
        self._connection.execute(
            "UPDATE card_mapping_candidate SET candidates_fetched_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), mapping_candidate_id),
        )
        self._connection.commit()

    def _select_pending(
        self, columns: str, limit: int | None, extra_where: str = ""
    ) -> tuple[dict, ...]:
        query = (
            f"SELECT {columns} FROM card_mapping_candidate "
            f"WHERE status = ? {extra_where} {_STABLE_ORDER}"
        )
        parameters: tuple = (STATUS_PENDING,)
        if limit is not None:
            query += " LIMIT ?"
            parameters += (limit,)
        return tuple(
            dict(row) for row in self._connection.execute(query, parameters).fetchall()
        )

    def _candidates_of(self, mapping_candidate_id: int) -> tuple[dict, ...]:
        rows = self._connection.execute(
            "SELECT apparel_id, name_en, name_ja, card_code, image_url "
            "FROM card_candidate WHERE mapping_candidate_id = ? ORDER BY id",
            (mapping_candidate_id,),
        ).fetchall()
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
