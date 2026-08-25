"""把 Notion 匯出的持有品一次性匯入資料庫。"""

import hashlib
from pathlib import Path

from .holdings import HoldingRepository
from .notion_csv import HoldingImportError, read_holdings
from .repository import MappingCandidateRepository


class HoldingImportService:
    def __init__(
        self,
        holdings: HoldingRepository,
        mapping: MappingCandidateRepository,
    ) -> None:
        self._holdings = holdings
        self._mapping = mapping

    def import_once(self, csv_path: Path) -> None:
        """已匯過就跳過。不比對指紋、不做增量對齊——理由見 db.py 的表註解。"""
        if self._holdings.has_completed_import():
            return
        kind_ids = self._mapping.ids_by_kind()
        rows = [
            (self._kind_id(kind_ids, row.kind_key, row.source_row_number), row)
            for row in read_holdings(csv_path)
        ]
        self._holdings.import_batch(rows, str(csv_path), _fingerprint(csv_path))

    @staticmethod
    def _kind_id(
        kind_ids: dict[tuple[str, str, str], int],
        kind_key: tuple[str, str, str],
        row_number: int,
    ) -> int:
        """卡種列與持有品讀的是同一份 CSV，對不到就是內部狀態壞了，不吞。"""
        if kind_key not in kind_ids:
            raise HoldingImportError(
                f"第 {row_number} 列（{' '.join(kind_key)}）對不到卡種列"
            )
        return kind_ids[kind_key]


def _fingerprint(csv_path: Path) -> str:
    return hashlib.sha256(csv_path.read_bytes()).hexdigest()
