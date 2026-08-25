"""待確認卡種與 SNKRDUNK 候選之間的協調。"""

from .images import CardImageError, CardImageStore
from .repository import MappingCandidateRepository
from .snkrdunk import SnkrdunkClient, SnkrdunkError

# 一次只為一批列取候選——共識書要的是「附卡圖分批送出」，不是一次打 70 個請求。
DEFAULT_BATCH_SIZE = 20


class MappingService:
    def __init__(
        self,
        repository: MappingCandidateRepository,
        snkrdunk: SnkrdunkClient,
        images: CardImageStore,
    ) -> None:
        self._repository = repository
        self._snkrdunk = snkrdunk
        self._images = images

    def fetch_candidates(self, mapping_candidate_id: int) -> None:
        """為單一列向 SNKRDUNK 取候選。已取過的不再取。"""
        row = self._repository.find_pending(mapping_candidate_id)
        if row is None or row["candidates_fetched_at"] is not None:
            return
        self._record(row)

    def ensure_candidates(self, limit: int = DEFAULT_BATCH_SIZE) -> None:
        """為**即將顯示的那一批**補齊候選。

        補的必須是要顯示的那些列。若改成「任何還沒抓過的一批」，畫面上看到的
        永遠是空的，而每次載入都在背地裡抓下一批——測試會綠，人卻等到天荒地老。
        """
        for row in self._repository.list_pending(limit=limit):
            if row["candidates_fetched_at"] is None:
                self._record(row)

    def _record(self, row: dict) -> None:
        candidates = self._snkrdunk.search_candidates(
            row["series_normalized"], row["number_normalized"]
        )
        self._repository.record_candidates(row["id"], candidates)

    def confirm(self, row: dict, apparel_id: int) -> None:
        """取回 productCatalogId 並寫入卡種主檔。

        取不到就整筆失敗——用 apparel id 去打成交紀錄端點會回 200 與空資料而
        不報錯（ADR-0007），所以絕不寫入 product_catalog_id 為空的卡種。
        """
        apparel = self._snkrdunk.fetch_apparel(apparel_id)
        if apparel.product_catalog_id is None:
            raise SnkrdunkError(
                f"SNKRDUNK 的 apparel {apparel_id} 沒有 productCatalogId，無法確認"
            )
        self._repository.confirm(row, apparel)
        try:
            self.store_card_image(apparel.apparel_id)
        except (SnkrdunkError, CardImageError):
            # 卡圖是裝飾，productCatalogId 才是命脈。一張圖沒拉下來不該
            # 逼使用者重新確認一次——留著缺失標記，事後補即可。
            pass

    def store_card_image(self, apparel_id: int) -> str:
        card = self._repository.find_card(apparel_id)
        if card is None:
            raise CardImageError(f"卡種主檔沒有 apparel {apparel_id}")
        data = self._snkrdunk.download(card["image_url"])
        path = self._images.save(apparel_id, data)
        self._repository.record_card_image(apparel_id, str(path))
        return str(path)
