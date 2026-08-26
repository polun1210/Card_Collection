"""SNKRDUNK 的唯一對外窗口。

搜尋走 `/search?keywords=<系列> <卡號>`——這頁是伺服器端渲染，結果就在 HTML 裡，
不需要 API 金鑰也不需要瀏覽器自動化。參數名是 **keywords（複數）**，單數的
`keyword` 會被忽略並回傳一份與關鍵字無關的推薦清單，是會安靜說謊的那種錯。

卡號必須先補零至三位：實測 `S8a 1` 回 0 筆、`S8a 001` 回 5 筆。

卡種明細走 `/v1/apparels/{id}`，提供英文卡名、日文卡名與官方去背卡圖。

成交紀錄走 `/v3/products/{productCatalogId}/trading-history`（ADR-0007）。路徑上
的 id 是 **productCatalogId**，不是 apparel id——用後者去打會回 200 與一份空資料，
不會報錯。
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

BASE_URL = "https://snkrdunk.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
MAX_CANDIDATES = 8
PSA10_CONDITION_CODE = "trading_card_single_psa10"
SINGLE_CARD_VARIANT_NAME = "1枚"

_APPAREL_LINK = re.compile(r"https://snkrdunk\.com/apparels/(\d+)")
_CARD_CODE = re.compile(r"\[([^\]]+)\]")


class SnkrdunkError(RuntimeError):
    """SNKRDUNK 回了非預期的結果。絕不靜默略過——安靜的錯最難查。"""


@dataclass(frozen=True)
class Apparel:
    apparel_id: int
    name_en: str
    name_ja: str
    card_code: str
    image_url: str
    # 確認時才需要，取不到就不能寫進卡種主檔（ADR-0007）。
    product_catalog_id: int | None


@dataclass(frozen=True)
class Trade:
    """一筆成交明細。原幣金額與 SNKRDUNK 的原始文字一律原樣帶著走。"""

    price_jpy: int
    sold_at_raw: str
    condition_raw: str
    variant_raw: str

    @property
    def is_single_card(self) -> bool:
        return self.variant_raw.replace(" ", "") == SINGLE_CARD_VARIANT_NAME


@dataclass(frozen=True)
class TradingHistory:
    """`trades` 固定最多 20 筆且無分頁，`chart` 是每日聚合、不得當成交寫入。"""

    trades: tuple[Trade, ...]
    single_card_variant_id: int | None

    @property
    def is_all_single_cards(self) -> bool:
        return all(trade.is_single_card for trade in self.trades)


class SnkrdunkClient:
    """對 SNKRDUNK 的請求一律序列化，且每次之間留固定間隔。"""

    def __init__(
        self,
        client: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
        request_interval: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._request_interval = request_interval
        self._has_requested = False

    def search_candidates(self, series: str, number: str) -> tuple[Apparel, ...]:
        apparel_ids = self._search_apparel_ids(f"{series} {number}")
        return tuple(
            self.fetch_apparel(apparel_id)
            for apparel_id in apparel_ids[:MAX_CANDIDATES]
        )

    def _search_apparel_ids(self, keywords: str) -> list[int]:
        response = self._get("/search", params={"keywords": keywords})
        found = (int(match) for match in _APPAREL_LINK.findall(response.text))
        return list(dict.fromkeys(found))

    def fetch_apparel(self, apparel_id: int) -> Apparel:
        payload = self._get(
            f"/v1/apparels/{apparel_id}", headers={"Accept": "application/json"}
        ).json()
        name_en = payload.get("name") or ""
        image_url = (payload.get("primaryMedia") or {}).get("imageUrl") or ""
        if not name_en or not image_url:
            raise SnkrdunkError(f"SNKRDUNK 的 apparel {apparel_id} 缺少卡名或卡圖")
        card_code = _CARD_CODE.search(name_en)
        return Apparel(
            apparel_id=apparel_id,
            name_en=name_en,
            name_ja=payload.get("localizedName") or "",
            card_code=card_code.group(1) if card_code else "",
            image_url=image_url,
            product_catalog_id=payload.get("productCatalogId"),
        )

    def fetch_trading_history(
        self, product_catalog_id: int, variant_id: int | None = None
    ) -> TradingHistory:
        """PSA 10 的成交明細。省略 variant_id 即不篩枚数，會混入多張一組。"""
        params: dict[str, str | int] = {"condition_code": PSA10_CONDITION_CODE}
        if variant_id is not None:
            params["variant_id"] = variant_id
        payload = self._get(
            f"/v3/products/{product_catalog_id}/trading-history",
            params=params,
            headers={"Accept": "application/json"},
        ).json()
        return TradingHistory(
            trades=tuple(
                _to_trade(raw, product_catalog_id)
                for raw in (payload.get("trades") or [])
            ),
            single_card_variant_id=_single_card_variant_id(payload),
        )

    def download(self, url: str) -> bytes:
        """下載 CDN 上的卡圖。網址是絕對路徑，不掛在 snkrdunk.com 底下。"""
        return self._request(url).content

    def _get(self, path: str, **kwargs) -> httpx.Response:
        return self._request(BASE_URL + path, **kwargs)

    def _request(self, url: str, **kwargs) -> httpx.Response:
        if self._has_requested:
            self._sleep(self._request_interval)
        self._has_requested = True
        try:
            response = self._client.get(url, **kwargs)
        except httpx.HTTPError as error:
            raise SnkrdunkError(f"SNKRDUNK 請求失敗：{url}") from error
        if response.status_code != httpx.codes.OK:
            raise SnkrdunkError(f"SNKRDUNK 回應 {response.status_code}：{url}")
        return response


def _to_trade(raw: dict, product_catalog_id: int) -> Trade:
    """缺價格或成交時間就整張卡失敗。補一個猜的數字進去比抓不到更糟。"""
    price = raw.get("price")
    sold_at = raw.get("soldAt")
    if price is None or not sold_at:
        raise SnkrdunkError(
            f"SNKRDUNK 的成交紀錄 {product_catalog_id} 有一筆缺少價格或成交時間"
        )
    return Trade(
        price_jpy=int(price),
        sold_at_raw=str(sold_at),
        condition_raw=str(raw.get("title") or ""),
        variant_raw=str(raw.get("label") or ""),
    )


def _single_card_variant_id(payload: dict) -> int | None:
    """filters 是 dict 不是 list：枚数選項在 filters.variants.options。"""
    variants = (payload.get("filters") or {}).get("variants") or {}
    for option in variants.get("options") or []:
        if str(option.get("name") or "").replace(" ", "") == SINGLE_CARD_VARIANT_NAME:
            return option.get("id")
    return None
