"""行情爬取的協調：成交紀錄進來、換算成台幣、算出市值。

爬取**不掛在啟動流程上**——行情是會變的資料，不適合當開機條件，SNKRDUNK 掛掉不
該讓服務起不來。但它**接排程**：SNKRDUNK 的成交紀錄固定最多 20 筆且無分頁，漏掉
一天，那天的成交就永久消失（ADR-0007、ADR-0019）。觸發來源有兩個——畫面上的按鈕
與排程叫起來的 CLI——兩者都與服務的生命週期無關。

自動化必須配可觀測性：每一輪都寫進爬取帳本，並對外送出心跳。少了它們，來源改版
或被擋時畫面只會靜靜停在三週前（共識書 C6）。

單一卡種失敗只影響那一張，其餘照跑；失敗的明確列在結果裡並附上原因，絕不靜默
吞掉。跳過的（尚未對應到 SNKRDUNK 的卡種）也一樣要列出來。
"""

from collections.abc import Callable
from datetime import date, datetime

from .crawl_runs import TRIGGER_MANUAL, CrawlOutcome, CrawlRunRepository
from .fx import FxRateService, to_twd
from .heartbeat import Heartbeat
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
        runs: CrawlRunRepository,
        heartbeat: Heartbeat,
        clock: Callable[[], datetime],
    ) -> None:
        self._cards = cards
        self._sales = sales
        self._snkrdunk = snkrdunk
        self._fx = fx
        self._runs = runs
        self._heartbeat = heartbeat
        self._clock = clock

    # --- 爬取 -----------------------------------------------------------

    def crawl(self, trigger: str = TRIGGER_MANUAL) -> dict:
        """跑一輪全量爬取。回傳這一輪到底做了什麼，好與壞都寫在裡面。

        帳本先開、心跳後送：`start()` 若因為已有一輪在跑而擋下來，**一個對外請求
        都還沒送出**——重複觸發不會變成對 SNKRDUNK 的雙倍流量。

        整輪炸掉時，帳本一定要收到 `failed` 才能讓例外繼續往上丟。少了這一步，那
        一列會永遠停在 `running`，既冒充「還在跑」，又把鎖一直握著。
        """
        run_id = self._runs.start(trigger, self._clock())
        self._heartbeat.started()
        try:
            report = self._crawl_once()
        except Exception as error:
            self._runs.fail(run_id, str(error), self._clock())
            self._heartbeat.failed(str(error))
            raise
        outcome = CrawlOutcome.from_report(report)
        self._runs.finish(run_id, outcome, self._clock())
        self._heartbeat.succeeded(outcome)
        return {**report, "run_id": run_id}

    def _crawl_once(self) -> dict:
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

    def active_sales(self) -> dict[int, list[dict]]:
        """參與計算的成交紀錄，依卡種分組、日期升冪。

        走勢圖要的是**原料**而不是算好的市值：它得自己把每一天以前的那一段切出
        來，才不會讓未來的成交洩漏進過去的某一天。
        """
        return self._sales.active_by_apparel()

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
