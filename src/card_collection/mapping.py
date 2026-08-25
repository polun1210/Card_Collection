"""待確認卡種與 SNKRDUNK 候選之間的協調。"""

from .repository import MappingCandidateRepository
from .snkrdunk import SnkrdunkClient

# 一次只為一批列取候選——共識書要的是「附卡圖分批送出」，不是一次打 70 個請求。
DEFAULT_BATCH_SIZE = 20


class MappingService:
    def __init__(
        self, repository: MappingCandidateRepository, snkrdunk: SnkrdunkClient
    ) -> None:
        self._repository = repository
        self._snkrdunk = snkrdunk

    def fetch_candidates(self, mapping_candidate_id: int) -> None:
        """為單一列向 SNKRDUNK 取候選。已取過的不再取。"""
        row = self._repository.find_pending(mapping_candidate_id)
        if row is None or row["candidates_fetched_at"] is not None:
            return
        self._record(row)

    def ensure_candidates(self, limit: int = DEFAULT_BATCH_SIZE) -> None:
        """把還沒取過候選的列補齊，一次最多一批。"""
        for row in self._repository.list_without_candidates(limit=limit):
            self._record(row)

    def _record(self, row: dict) -> None:
        candidates = self._snkrdunk.search_candidates(
            row["series_normalized"], row["number_normalized"]
        )
        self._repository.record_candidates(row["id"], candidates)
