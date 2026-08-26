"""待確認卡種的讀寫介面。業務邏輯只認這個介面，不認 SQL。"""

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime

from .normalization import normalize_card_number, normalize_series
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


class CardKindExists(Exception):
    """這個卡種已經有一列了。帶著既有那一列的 id，讓呼叫端說得出是哪一個。

    兩個代表同一張卡的卡種列會讓持有品分裂到兩邊，市值也跟著分裂——而且兩邊看起來
    都是對的。
    """

    def __init__(self, existing_id: int) -> None:
        super().__init__(f"這個卡種已經在清單裡（第 {existing_id} 列）")
        self.existing_id = existing_id


class MappingCandidateRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_kind(
        self, series_raw: str, number_raw: str, card_name_raw: str
    ) -> int:
        """手動新增一個卡種列，狀態為待確認。

        新的卡種因此自動落進既有的待確認清單，沿用已經寫好的搜尋 → 確認 → 抓卡圖
        流程。正規化規則與 `seed()` 共用，系列代碼一樣永不收斂（ADR-0011）。
        """
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT INTO card_mapping_candidate
                        (series_raw, number_raw, card_name_raw,
                         series_normalized, number_normalized, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        series_raw,
                        number_raw,
                        card_name_raw,
                        normalize_series(series_raw),
                        normalize_card_number(number_raw),
                        STATUS_PENDING,
                    ),
                )
        except sqlite3.IntegrityError as error:
            existing = self.ids_by_kind().get(
                (series_raw, number_raw, card_name_raw)
            )
            raise CardKindExists(existing or 0) from error
        return int(cursor.lastrowid)

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

    def find_kind(self, row_id: int) -> dict | None:
        """依 id 取卡種列，**不限狀態**——未確認的卡種也能掛持有品。

        記一筆購入不該被「行情對應還沒做完」擋住。
        """
        row = self._connection.execute(
            f"SELECT {_QUEUE_COLUMNS} FROM card_mapping_candidate WHERE id = ?",
            (row_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def list_kinds(self) -> tuple[dict, ...]:
        """全部卡種列，含未確認與已否決的。供新增持有品時挑選。

        未確認的也要列出來——記一筆購入不該被「行情對應還沒做完」擋住。
        """
        rows = self._connection.execute(
            f"SELECT {_QUEUE_COLUMNS} FROM card_mapping_candidate {_STABLE_ORDER}"
        )
        return tuple(dict(row) for row in rows)

    def ids_by_kind(self) -> dict[tuple[str, str, str], int]:
        """卡種原始三元組 → 卡種列 id，含已確認、已否決與待處理的列。"""
        rows = self._connection.execute(
            "SELECT id, series_raw, number_raw, card_name_raw "
            "FROM card_mapping_candidate"
        )
        return {
            (row["series_raw"], row["number_raw"], row["card_name_raw"]): row["id"]
            for row in rows
        }

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
        """推翻確認：該列回到待處理，主檔中對應的卡種與其成交紀錄一併移除。

        成交紀錄跟著走是刻意的——它是依這份對應關係抓來的，對應被推翻就代表那些
        行情抓錯了卡。三件事同一個交易，不留「卡種沒了、行情還在」的半成品。
        持有品不在此列：它掛在卡種列上，你手上的實體卡不會因為重對而消失。
        """
        with self._connection:
            row = self._connection.execute(
                "SELECT apparel_id FROM card WHERE mapping_candidate_id = ?",
                (mapping_candidate_id,),
            ).fetchone()
            if row is None:
                return False
            self._connection.execute(
                "DELETE FROM sale WHERE apparel_id = ?", (row["apparel_id"],)
            )
            self._connection.execute(
                "DELETE FROM card WHERE mapping_candidate_id = ?",
                (mapping_candidate_id,),
            )
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

    def list_unconfirmed(self) -> tuple[dict, ...]:
        """還沒對應到 SNKRDUNK 的卡種。爬取跑不到它們，結果裡要明確列為跳過。"""
        rows = self._connection.execute(
            "SELECT id, series_raw, number_raw, card_name_raw, status "
            f"FROM card_mapping_candidate WHERE status != ? {_STABLE_ORDER}",
            (STATUS_CONFIRMED,),
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
