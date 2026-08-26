"""跑一輪全量行情爬取。這是排程每天叫起來的那支腳本。

**這支腳本會對外發送網路請求，也會寫入資料庫。**

    uv run python scripts/crawl.py --dry-run   # 只列出會跑哪些卡種，不發任何請求
    uv run python scripts/crawl.py             # 真的跑一輪

它存在的理由：SNKRDUNK 的成交紀錄固定最多 20 筆且無分頁，實測 68 個卡種裡有 13 張
的 20 筆只涵蓋 3 天以內、2 張全部落在同一天。**漏掉一天，那天的成交就永久消失**
（ADR-0007、ADR-0019）。

結束碼刻意分開，好讓 Windows 工作排程器的執行歷程分得出發生什麼事：

    0  一輪跑完，沒有卡種失敗
    1  整輪失敗（來源掛了、資料庫寫不進去……）
    2  跑完了，但有卡種失敗
    3  已經有一輪在跑，這次什麼都沒做

輸出同時寫到畫面與 `data/logs/crawl-YYYY-MM-DD.log`。
"""

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from card_collection.config import (  # noqa: E402
    DEFAULT_DB_PATH,
    DEFAULT_IMAGES_DIR,
    DEFAULT_LOG_DIR,
)
from card_collection.crawl_runs import TRIGGER_SCHEDULED, CrawlRunInProgress  # noqa: E402
from card_collection.heartbeat import Heartbeat  # noqa: E402
from card_collection.services import build_services  # noqa: E402

EXIT_OK = 0
EXIT_RUN_FAILED = 1
EXIT_CARDS_FAILED = 2
EXIT_ALREADY_RUNNING = 3


class Log:
    """同時寫畫面與檔案。

    排程跑的時候沒有人在看畫面，所以檔案是唯一留得下來的紀錄；手動跑的時候人在
    看畫面，所以兩邊都要有。
    """

    def __init__(self, log_dir: Path, clock: Callable[[], datetime]) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._path = log_dir / f"crawl-{clock().date().isoformat()}.log"
        self._handle = self._path.open("a", encoding="utf-8")

    @property
    def path(self) -> Path:
        return self._path

    def __call__(self, message: str) -> None:
        stamped = f"{self._clock().isoformat(timespec='seconds')}  {message}"
        print(stamped)
        self._handle.write(stamped + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def main(
    dry_run: bool = False,
    db_path: Path = DEFAULT_DB_PATH,
    images_dir: Path = DEFAULT_IMAGES_DIR,
    log_dir: Path = DEFAULT_LOG_DIR,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    fx_download: Callable[[], bytes] | None = None,
    heartbeat: Heartbeat | None = None,
) -> int:
    """跑一輪，回傳結束碼。

    後五個參數是測試接縫，與 `create_app()` 保持同一組——正式執行一個都不用傳。
    結束碼是工作排程器唯一看得到的訊號，因此它由**真正的進入點**測，不是由某個
    內部函式測。
    """
    log = Log(log_dir, clock)
    services = build_services(
        db_path=db_path,
        images_dir=images_dir,
        transport=transport,
        sleep=sleep,
        clock=clock,
        fx_download=fx_download,
        heartbeat=heartbeat,
    )
    try:
        return _run(services, log, dry_run)
    finally:
        services.close()
        log.close()


def _run(services, log: Log, dry_run: bool) -> int:
    cards = services.cards.list_cards()
    if dry_run:
        # 只讀資料庫，一個對外請求都不發——設定排程時用它驗證路徑與環境。
        log(f"--dry-run：會爬 {len(cards)} 個已確認的卡種，不發送任何對外請求。")
        for card in cards:
            log(
                f"  {card['series_raw']} #{card['number_raw']} "
                f"{card['card_name_raw']}（productCatalogId "
                f"{card['product_catalog_id']}）"
            )
        log(f"心跳：{'已設定' if services.heartbeat.is_configured else '未設定（不會送出任何通知）'}")
        log(f"log 檔：{log.path}")
        return EXIT_OK

    log(f"開始一輪爬取：{len(cards)} 個已確認的卡種。")
    try:
        report = services.market.crawl(trigger=TRIGGER_SCHEDULED)
    except CrawlRunInProgress as error:
        # 不是失敗，是這次沒得跑。說成失敗會讓排程歷程長出假的紅字。
        log(f"跳過：{error}")
        return EXIT_ALREADY_RUNNING
    except Exception as error:  # noqa: BLE001 — 整輪失敗要留下紀錄再往上報
        log(f"整輪失敗：{error}")
        return EXIT_RUN_FAILED

    totals = report["totals"]
    log(
        f"完成（run {report['run_id']}）："
        f"卡種 {totals['cards']} 個、抓到 {totals['fetched']} 筆、"
        f"新增 {totals['inserted']} 筆、待審 {totals['quarantined']} 筆、"
        f"跳過 {totals['skipped']} 個。"
    )
    log(f"匯率換算 {report['fx']['converted']} 筆。")
    if report["fx"]["error"]:
        # 匯率抓不到是外部故障，不是資料問題。它會在下一輪自動重試（ADR-0016），
        # 所以不算失敗，但一定要說出來。
        log(f"匯率沒抓到：{report['fx']['error']}——成交已用日圓原幣入庫，一筆都沒丟。")
    for failure in report["failed"]:
        log(
            f"卡種失敗：{failure['series_raw']} #{failure['number_raw']} "
            f"{failure['card_name_raw']}——{failure['reason']}"
        )
    return EXIT_CARDS_FAILED if report["failed"] else EXIT_OK


if __name__ == "__main__":
    unknown = [arg for arg in sys.argv[1:] if arg != "--dry-run"]
    if unknown:
        raise SystemExit(f"不認得的參數：{' '.join(unknown)}\n用法：見本檔開頭")
    raise SystemExit(main(dry_run="--dry-run" in sys.argv[1:]))
