"""心跳：對外送出「我還活著」，讓外部服務抓得到**沉默**。

爬取跑了但出錯，帳本記得住；爬取**根本沒跑**（電腦關機、排程被停用、腳本崩潰），
帳本什麼也不會有——出事的行程沒辦法通知你它沒跑起來。死人開關（dead man's
switch）判斷的是「該來的心跳沒來」，所以它是唯一抓得到這種沉默的機制。

**隱私界線**：ping 只夾帶爬取的**健康狀態**——幾個卡種、抓到幾筆、新增幾筆、
待審幾筆、哪幾張卡失敗與原因。**任何金額都不出門**：市值、成本、售出價、損益
一律不送。訊息由具名欄位逐個組出來，絕不整包 dump 任何字典，因為 dump 會在日後
有人往那個字典加欄位時，安靜地把新欄位一起送出去。

**ping URL 等同密碼**，知道的人可以偽造心跳讓你以為一切正常，所以它**絕不 commit
進 repo**——正式執行時由 `Heartbeat.from_env()` 從環境變數
`CARD_COLLECTION_HEALTHCHECK_URL` 讀進來。空字串與未設定一視同仁（都當沒設定），
這條規則屬於「心跳」這個概念，所以留在本模組。

**「要不要去讀那個環境變數」則是組裝層的事**：`Heartbeat(url=...)` 只認明確的
網址，`url=None` 的唯一意思就是「明確關閉、完全不要送」。呼叫端因此有辦法表達
「這台機器沒設定心跳」——否則傳 `None` 會拿回開發者的真實設定，測試結果就取決於
跑測試的人的環境變數（issue #18）。未設定就是 no-op——本機開發與測試不受影響，
也不會誤送。
"""

import os
from collections.abc import Callable

from .crawl_runs import CrawlOutcome

ENV_URL = "CARD_COLLECTION_HEALTHCHECK_URL"
TIMEOUT_SECONDS = 10

Send = Callable[[str, str], None]


def http_send(url: str, body: str) -> None:
    """真正送出去的那一下。獨立成函式，測試才有接縫可換。"""
    import httpx

    httpx.post(url, content=body.encode("utf-8"), timeout=TIMEOUT_SECONDS)


class Heartbeat:
    def __init__(
        self,
        url: str | None = None,
        send: Send = http_send,
        log: Callable[[str], None] = print,
    ) -> None:
        self._url = url
        self._send = send
        self._log = log

    @classmethod
    def from_env(cls) -> "Heartbeat":
        """正式執行的入口：從環境變數讀出 ping 網址來組一個心跳。

        `or None` 不能拿掉——環境變數存在但是空字串，代表的是「沒設定」而不是
        「網址就是空字串」。這個判斷屬於心跳自己，不外流給組裝層。
        """
        return cls(url=os.environ.get(ENV_URL) or None)

    @property
    def is_configured(self) -> bool:
        return self._url is not None

    def started(self) -> None:
        self._ping("/start", "")

    def succeeded(self, outcome: CrawlOutcome) -> None:
        self._ping("", summarize(outcome))

    def failed(self, reason: str) -> None:
        self._ping("/fail", reason)

    def _ping(self, suffix: str, body: str) -> None:
        """**心跳失敗不能讓爬取失敗。**

        通知管道掛掉不該反過來弄壞資料——爬取已經跑完、成交已經入庫，這時候丟出
        例外只會把一次成功的更新變成失敗。這是本模組唯一允許吞例外的地方，而且
        吞掉之後一定寫進 log，不留下無聲的失敗。
        """
        if self._url is None:
            return
        try:
            self._send(self._url + suffix, body)
        except Exception as error:  # noqa: BLE001 — 見上方 docstring
            self._log(f"心跳送不出去（{self._url + suffix}）：{error}")


def summarize(outcome: CrawlOutcome) -> str:
    """健康狀態的白話摘要。**逐個欄位具名取用，永不整包 dump。**"""
    lines = [
        f"卡種 {outcome.card_count} 個、抓到 {outcome.fetched} 筆、"
        f"新增 {outcome.inserted} 筆",
        f"待審 {outcome.quarantined} 筆、跳過 {outcome.skipped_count} 個、"
        f"匯率換算 {outcome.fx_converted} 筆",
    ]
    if outcome.fx_error:
        lines.append(f"匯率來源：{outcome.fx_error}")
    for failure in outcome.failures:
        lines.append(
            f"失敗：{failure['series_raw']} #{failure['number_raw']} "
            f"{failure['card_name_raw']}——{failure['reason']}"
        )
    return "\n".join(lines)
