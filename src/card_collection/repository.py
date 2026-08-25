"""待確認卡種的讀寫介面。業務邏輯只認這個介面，不認 SQL。"""

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime

from .notion_csv import CardKind
from .snkrdunk import Apparel

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

    def record_candidates(
        self, mapping_candidate_id: int, candidates: Iterable[Apparel]
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

    def _select_pending(self, columns: str, limit: int | None) -> tuple[dict, ...]:
        query = (
            f"SELECT {columns} FROM card_mapping_candidate "
            f"WHERE status = ? {_STABLE_ORDER}"
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

    def confirm(self, row: dict, apparel: Apparel) -> None:
        """寫入卡種主檔並把該列標為已確認。兩件事同一個交易，不留半成品。"""
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO card
                    (apparel_id, product_catalog_id, name_en, name_ja, card_code,
                     image_url, series_raw, number_raw, card_name_raw,
                     mapping_candidate_id, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    apparel.apparel_id,
                    apparel.product_catalog_id,
                    apparel.name_en,
                    apparel.name_ja,
                    apparel.card_code,
                    apparel.image_url,
                    row["series_raw"],
                    row["number_raw"],
                    row["card_name_raw"],
                    row["id"],
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._connection.execute(
                "UPDATE card_mapping_candidate SET status = ?, confirmed_apparel_id = ? "
                "WHERE id = ?",
                (STATUS_CONFIRMED, apparel.apparel_id, row["id"]),
            )

    def reject(self, mapping_candidate_id: int) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE card_mapping_candidate SET status = ? WHERE id = ?",
                (STATUS_REJECTED, mapping_candidate_id),
            )

    def undo_confirm(self, mapping_candidate_id: int) -> bool:
        """推翻確認：該列回到待處理，主檔中對應的卡種被移除。"""
        with self._connection:
            deleted = self._connection.execute(
                "DELETE FROM card WHERE mapping_candidate_id = ?",
                (mapping_candidate_id,),
            ).rowcount
            if not deleted:
                return False
            self._connection.execute(
                "UPDATE card_mapping_candidate "
                "SET status = ?, confirmed_apparel_id = NULL WHERE id = ?",
                (STATUS_PENDING, mapping_candidate_id),
            )
        return True

    def record_card_image(self, apparel_id: int, image_path: str) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE card SET image_local_path = ? WHERE apparel_id = ?",
                (image_path, apparel_id),
            )

    def find_card(self, apparel_id: int) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM card WHERE apparel_id = ?", (apparel_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_cards(self) -> tuple[dict, ...]:
        rows = self._connection.execute(
            "SELECT * FROM card ORDER BY series_raw, number_raw, card_name_raw"
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
