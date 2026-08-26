"""JPY→TWD 匯率：臺灣銀行牌告的取得、保存與查用。

來源為臺銀日圓近六個月牌告 CSV，採**即期買入**價（ADR-0014）。它對應的情境是
「把卡在日本賣掉、把日圓換回台幣」，也是候選欄位中最保守的一個。

請求走 curl_cffi 並模擬 Chrome 的 TLS 指紋——臺銀掛的是 Akamai Bot Manager，
只帶一個 User-Agent 會被擋（ADR-0017）。

三件事在這個模組裡是紀律而不是最佳化：

1. **200 不等於有資料。** 機器人驗證頁同樣是 200，只有內容看得出來。若把它讀成
   「查無匯率」，成交會被送進待審、看起來像資料問題，實際上是被擋——那是安靜說謊
   的變體。失敗一律帶著原因往上送，不吞。
2. **中英文牌告都要認得。** 臺銀依 Accept-Language 決定 CSV 用哪種語言，欄位位置
   與數值完全相同，只有方向欄是「本行買入」或「Buying」。只認一種就會在拿到真資料
   時回報「沒有任何日圓牌告」。
3. **寫入即固定。** 已存在的日期永不覆寫，昨天看到的數字今天不會變（ADR-0006）。
"""

import csv
import io
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from curl_cffi import requests as curl_requests

BOT_L6M_JPY_URL = "https://rate.bot.com.tw/xrt/flcsv/0/L6M/JPY"
# 同一個路徑把 L6M 換成 YYYY-MM，就是那個月的牌告，格式與 L6M 完全相同。
# 平常用不到——L6M 已涵蓋日常爬取；它是補登更早月份時的入口（ADR-0018）。
BOT_MONTH_JPY_URL = "https://rate.bot.com.tw/xrt/flcsv/0/{month}/JPY"
FX_SOURCE = "bot-spot-buy"
# curl_cffi 的模擬目標。它會連同 Chrome 的 header 組一起送，包含 Accept-Language，
# 所以中文牌告要另外指定——不指定會拿到英文版。
IMPERSONATE_TARGET = "chrome"
ACCEPT_LANGUAGE = "zh-TW,zh;q=0.9"
REQUEST_TIMEOUT_SECONDS = 30

_CURRENCY = "JPY"
# 中文牌告寫「本行買入」，英文牌告寫「Buying」。兩者是同一列的同一個欄位。
_BUY_ROW_MARKERS = ("本行買入", "Buying")
# 一列同時含買入與賣出：[3] 現金買入、[4] 即期買入、[13] 現金賣出、[14] 即期賣出。
_SPOT_BUY_COLUMN = 4
_DATE_COLUMN = 0
_CURRENCY_COLUMN = 1
_DIRECTION_COLUMN = 2

# 這些字串出現在回應裡，代表這個來源實際上沒給我們資料。狀態碼漂亮、內容是空的。
_NOT_ACTUALLY_DATA = (
    ("Challenge Validation", "被機器人驗證擋下"),
    ("sec-text-container", "被機器人驗證擋下"),
    ("找不到任何一筆資料", "臺銀回「查無資料」"),
)


class FxRateError(RuntimeError):
    """匯率來源沒給我們可用的資料。絕不退化成「查無匯率」。"""


@dataclass(frozen=True)
class FxRate:
    rate_date: str
    rate: float
    source: str


def parse_bot_csv(body: bytes) -> tuple[FxRate, ...]:
    """臺銀 L6M CSV → 逐營業日的即期買入價。內容不對就明確報錯，不回空清單。"""
    text = body.decode("utf-8-sig", errors="replace")
    for marker, why in _NOT_ACTUALLY_DATA:
        if marker in text:
            raise FxRateError(f"臺銀回應 200 但沒有資料：{why}")
    rates = tuple(
        rate
        for rate in (_to_rate(row) for row in csv.reader(io.StringIO(text)))
        if rate is not None
    )
    if not rates:
        raise FxRateError("臺銀回應裡沒有任何日圓牌告")
    return rates


def _to_rate(row: list[str]) -> FxRate | None:
    if len(row) <= _SPOT_BUY_COLUMN:
        return None
    if row[_CURRENCY_COLUMN].strip() != _CURRENCY:
        return None
    if row[_DIRECTION_COLUMN].strip() not in _BUY_ROW_MARKERS:
        return None
    try:
        rate_date = datetime.strptime(row[_DATE_COLUMN].strip(), "%Y%m%d").date()
        rate = float(row[_SPOT_BUY_COLUMN])
    except ValueError:
        return None
    return FxRate(rate_date=rate_date.isoformat(), rate=rate, source=FX_SOURCE)


class BotRateDownload:
    """臺銀的下載器。模擬 Chrome 的 TLS 指紋，否則會被 Akamai 擋下（ADR-0017）。"""

    def __init__(
        self, url: str = BOT_L6M_JPY_URL, impersonate: str = IMPERSONATE_TARGET
    ) -> None:
        self._url = url
        self._impersonate = impersonate

    def __call__(self) -> bytes:
        try:
            response = curl_requests.get(
                self._url,
                impersonate=self._impersonate,
                headers={"Accept-Language": ACCEPT_LANGUAGE},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except curl_requests.exceptions.RequestException as error:
            raise FxRateError(f"臺銀匯率請求失敗：{error}") from error
        if response.status_code != 200:
            raise FxRateError(f"臺銀匯率回應 {response.status_code}")
        return response.content


class FxRateRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def store(self, rates: Iterable[FxRate], fetched_at: str) -> int:
        """已存在的日期不覆寫——一經寫入即固定（ADR-0006）。"""
        rows = list(rates)
        with self._connection:
            self._connection.executemany(
                "INSERT INTO fx_rate (rate_date, rate, source, fetched_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (rate_date) DO NOTHING",
                [(r.rate_date, r.rate, r.source, fetched_at) for r in rows],
            )
        return len(rows)

    def on_or_before(self, on_date: str) -> dict | None:
        """週末與假日沒有牌告，沿用前一營業日（ADR-0014）。"""
        row = self._connection.execute(
            "SELECT rate_date, rate, source FROM fx_rate "
            "WHERE rate_date <= ? ORDER BY rate_date DESC LIMIT 1",
            (on_date,),
        ).fetchone()
        return dict(row) if row else None

    def record_fetch(
        self, requested_through: str, row_count: int, fetched_at: str
    ) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO fx_fetch (requested_through, source, row_count, fetched_at)"
                " VALUES (?, ?, ?, ?)",
                (requested_through, FX_SOURCE, row_count, fetched_at),
            )

    def fetched_through(self) -> str | None:
        row = self._connection.execute(
            "SELECT MAX(requested_through) AS through FROM fx_fetch"
        ).fetchone()
        return row["through"] if row else None


@dataclass(frozen=True)
class FxLookup:
    """一次查用的結果。查不到就是查不到，但**為什麼**查不到必須說得出來。"""

    rates: dict[str, dict | None]
    fetched: bool
    error: str | None


class FxRateService:
    """對外只有一個問題要回答：這幾天各自該用哪個匯率換算。"""

    def __init__(
        self, repository: FxRateRepository, download: Callable[[], bytes]
    ) -> None:
        self._repository = repository
        self._download = download

    def rates_for(self, dates: Iterable[str], now: datetime) -> FxLookup:
        """回傳每個日期實際採用的匯率列，查不到的給 None——絕不編一個數字。

        來源是一份六個月的整包 CSV，抓一天等於抓全部。「只抓需要的日期、抓過的
        不重抓」在這個形狀下就是：**需要的日期超出上次抓取的範圍才再抓一次**。
        """
        wanted = sorted(set(dates))
        if not wanted:
            return FxLookup(rates={}, fetched=False, error=None)
        fetched, error = self._refresh_if_needed(wanted[-1], now)
        return FxLookup(
            rates={
                on_date: self._repository.on_or_before(on_date) for on_date in wanted
            },
            fetched=fetched,
            error=error,
        )

    def _refresh_if_needed(
        self, needed_through: str, now: datetime
    ) -> tuple[bool, str | None]:
        fetched_through = self._repository.fetched_through()
        if fetched_through is not None and needed_through <= fetched_through:
            return False, None
        try:
            rates = parse_bot_csv(self._download())
        except FxRateError as error:
            # 抓不到就讓需要它的成交進待審，但原因一路帶回爬取結果，不吞。
            # 不記帳本，下一輪會再試一次。
            return True, str(error)
        fetched_at = now.isoformat()
        self._repository.store(rates, fetched_at)
        # 帳本只記到「實際拿到的最新牌告日」。成交當天臺銀還沒掛牌時（早於當日
        # 掛牌時間，或那天是假日），記成需要的日期會讓我們此後再也不去拿那天的
        # 牌告——已寫入的成交本來就固定不動，但當天後續的新成交會跟著一起舊。
        newest = max(rate.rate_date for rate in rates)
        self._repository.record_fetch(
            min(needed_through, newest), len(rates), fetched_at
        )
        return True, None


def to_twd(price_jpy: int, rate: float) -> int:
    """基準幣為新台幣整數。四捨五入到元，不留小數。"""
    return round(price_jpy * rate)
