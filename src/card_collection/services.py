"""服務組裝：資料庫連線、HTTP 用戶端、各 repository 與各 service 的接線。

三個入口會用到同一組物件——web 服務、排程爬取的 CLI、補登匯率的 CLI。**組裝規則
只能有一個地方說了算**，否則三個入口會各自漂移：某一個忘了開 WAL、某一個用了不同
的請求間隔，而這種漂移只會在正式跑的時候才現形。

這裡只做**組裝**，不做啟動儀式。卡種列的 seed 與持有品的一次性匯入屬於 web 服務
的啟動流程，留在 `app.py`——CLI 不該因為 CSV 有一列壞掉就爬不了行情。
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .crawl_runs import CrawlRunRepository
from .db import connect, create_schema
from .fx import BotRateDownload, FxRateRepository, FxRateService
from .heartbeat import Heartbeat
from .holdings import HoldingRepository
from .images import CardImageStore
from .mapping import MappingService
from .market import MarketService
from .repository import MappingCandidateRepository
from .sales import SaleRepository
from .snkrdunk import DEFAULT_REQUEST_INTERVAL_SECONDS, USER_AGENT, SnkrdunkClient


@dataclass
class Services:
    connection: object
    cards: MappingCandidateRepository
    holdings: HoldingRepository
    sales: SaleRepository
    runs: CrawlRunRepository
    mapping: MappingService
    market: MarketService
    heartbeat: Heartbeat
    clock: Callable[[], datetime]
    _http_client: httpx.Client

    def close(self) -> None:
        self._http_client.close()
        self.connection.close()


def build_services(
    db_path: Path,
    images_dir: Path,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    request_interval: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    fx_download: Callable[[], bytes] | None = None,
    heartbeat: Heartbeat | None = None,
) -> Services:
    """組好一整組服務。呼叫端負責在用完後呼叫 `close()`。

    匯率不走 httpx：臺銀需要模擬 Chrome 的 TLS 指紋，那是另一套 HTTP 堆疊，
    所以它的測試接縫在下載器本身，不在 httpx 的傳輸層（ADR-0017）。"""
    connection = connect(db_path)
    create_schema(connection)

    http_client = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30,
        follow_redirects=True,
        transport=transport,
    )
    snkrdunk = SnkrdunkClient(
        http_client, sleep=sleep, request_interval=request_interval
    )

    cards = MappingCandidateRepository(connection)
    sales = SaleRepository(connection)
    runs = CrawlRunRepository(connection)
    beat = heartbeat or Heartbeat.from_env()
    return Services(
        connection=connection,
        cards=cards,
        holdings=HoldingRepository(connection),
        sales=sales,
        runs=runs,
        mapping=MappingService(cards, snkrdunk, CardImageStore(images_dir)),
        market=MarketService(
            cards,
            sales,
            snkrdunk,
            FxRateService(
                FxRateRepository(connection), fx_download or BotRateDownload()
            ),
            runs=runs,
            heartbeat=beat,
            clock=clock,
        ),
        heartbeat=beat,
        clock=clock,
        _http_client=http_client,
    )
