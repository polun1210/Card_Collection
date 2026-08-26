"""行情爬取的協調：成交紀錄進來、換算成台幣、算出市值。

爬取由**手動觸發**，不接排程、不掛在啟動流程上。行情是會變的資料，不適合當開機
條件——SNKRDUNK 掛掉不該讓服務起不來。

單一卡種失敗只影響那一張，其餘照跑；失敗的明確列在結果裡並附上原因，絕不靜默
吞掉。跳過的（尚未對應到 SNKRDUNK 的卡種）也一樣要列出來。
"""

from collections.abc import Callable
from datetime import date, datetime

from .fx import FxRateService, to_twd
from .repository import MappingCandidateRepository
from .sales import (
    JST,
    QUARANTINE_FX_SOURCE_DOWN,
    QUARANTINE_NO_FX_RATE,
    SaleRepository,
    market_value,
    market_values,
    to_pending_sales,
)
from .snkrdunk import SnkrdunkClient, SnkrdunkError, Trade

SKIP_NOT_CONFIRMED = "尚未確認對應到 SNKRDUNK 的卡種"


class MarketService:
    def __init__(
        self,
        cards: MappingCandidateRepository,
        sales: SaleRepository,
        snkrdunk: SnkrdunkClient,
        fx: FxRateService,
        clock: Callable[[], datetime],
    ) -> None:
        self._cards = cards
        self._sales = sales
        self._snkrdunk = snkrdunk
        self._fx = fx
        self._clock = clock

    # --- 爬取 -----------------------------------------------------------

    def crawl(self) -> dict:
        """跑一輪全量爬取。回傳這一輪到底做了什麼，好與壞都寫在裡面。"""
        now = self._clock()
        crawled, failed = self._fetch_all(now)
        fx = self.convert_pending(now)
        quarantined = self._sales.quarantined_counts()
        cards = [
            {**card, "quarantined": quarantined.get(card["apparel_id"], 0)}
            for card in crawled
        ]
        skipped = self._skipped()
        return {
            "crawled_at": now.isoformat(),
            "cards": cards,
            "failed": failed,
            "skipped": skipped,
            "fx": fx,
            "totals": {
                "cards": len(cards),
                "fetched": sum(card["fetched"] for card in cards),
                "inserted": sum(card["inserted"] for card in cards),
                "quarantined": sum(card["quarantined"] for card in cards),
                "failed": len(failed),
                "skipped": len(skipped),
            },
        }

    def _fetch_all(self, now: datetime) -> tuple[list[dict], list[dict]]:
        crawled: list[dict] = []
        failed: list[dict] = []
        for card in self._cards.list_cards():
            where = _card_summary(card)
            try:
                trades = self._single_card_trades(card["product_catalog_id"])
            except SnkrdunkError as error:
                # 一張卡的問題不讓整輪白跑，但它絕不會被讀成「這張卡沒有成交」。
                failed.append({**where, "reason": str(error)})
                continue
            pending = to_pending_sales(card["apparel_id"], trades)
            inserted = self._sales.insert_many(pending, now.isoformat())
            crawled.append({**where, "fetched": len(pending), "inserted": inserted})
        return crawled, failed

    def _single_card_trades(self, product_catalog_id: int) -> tuple[Trade, ...]:
        """先不篩枚数打一次；已經全是 1 枚就省下第二次請求。

        實測有三分之一的卡未篩選時就已全為 1 枚，第二次請求會拿回完全相同的結果。
        """
        history = self._snkrdunk.fetch_trading_history(product_catalog_id)
        if history.is_all_single_cards or history.single_card_variant_id is None:
            return history.trades
        filtered = self._snkrdunk.fetch_trading_history(
            product_catalog_id, history.single_card_variant_id
        )
        return filtered.trades

    def convert_pending(self, now: datetime) -> dict:
        """每筆成交以**成交當日**的匯率換算，寫入即固定（ADR-0006）。

        補登腳本也走這裡，不另外實作一份——換算規則只能有一個地方說了算。

        回傳這一輪匯率來源的狀況。抓不到就抓不到，但**為什麼**抓不到要說出來——
        把「被機器人驗證擋下」顯示成「查無成交當日匯率」，就是把外部故障說成資料
        問題（ADR-0014、ADR-0017）。
        """
        awaiting = self._sales.awaiting_rate()
        if not awaiting:
            return {"pending": 0, "fetched": False, "converted": 0, "error": None}
        lookup = self._fx.rates_for(
            (sale["sold_date_jst"] for sale in awaiting), now=now
        )
        # 來源整個拿不到，與「這個日期超出來源涵蓋範圍」是兩回事。前者下一輪成功時
        # 會被改寫成後者（若那天真的沒有牌告），所以標錯不會留著。
        reason = QUARANTINE_FX_SOURCE_DOWN if lookup.error else QUARANTINE_NO_FX_RATE
        converted = 0
        for sale in awaiting:
            rate = lookup.rates.get(sale["sold_date_jst"])
            if rate is None:
                # 抓不到匯率就進待審，絕不用今日匯率或任何編出來的數字硬換。
                self._sales.quarantine(sale["id"], reason)
                continue
            converted += 1
            self._sales.apply_rate(
                sale["id"],
                to_twd(sale["price_jpy"], rate["rate"]),
                rate["rate"],
                rate["rate_date"],
                rate["source"],
            )
        return {
            "pending": len(awaiting),
            "fetched": lookup.fetched,
            "converted": converted,
            "error": lookup.error,
        }

    def _skipped(self) -> list[dict]:
        return [
            {
                "series_raw": row["series_raw"],
                "number_raw": row["number_raw"],
                "card_name_raw": row["card_name_raw"],
                "reason": SKIP_NOT_CONFIRMED,
            }
            for row in self._cards.list_unconfirmed()
        ]

    # --- 市值 -----------------------------------------------------------

    def today(self) -> date:
        """成交日期一律以 JST 為準，「今天」也得用同一把尺量。"""
        return self._clock().astimezone(JST).date()

    def values(self) -> dict[int, dict]:
        return market_values(self._sales.active_by_apparel(), self.today())

    def value_for(self, apparel_id: int) -> dict | None:
        return market_value(self._sales.active_for_apparel(apparel_id), self.today())

    def quarantined(self) -> tuple[dict, ...]:
        return self._sales.list_quarantined()

    def sales_for(self, apparel_id: int) -> tuple[dict, ...]:
        return self._sales.list_for_apparel(apparel_id)


def _card_summary(card: dict) -> dict:
    return {
        "apparel_id": card["apparel_id"],
        "series_raw": card["series_raw"],
        "number_raw": card["number_raw"],
        "card_name_raw": card["card_name_raw"],
    }
