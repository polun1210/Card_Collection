"""補登某幾個月的臺銀日圓牌告，並把因此卡住的成交紀錄換算完成。

**這支腳本會對外發送網路請求，也會寫入資料庫**，請自行執行：

    uv run python scripts/backfill_fx_month.py 2026-02
    uv run python scripts/backfill_fx_month.py 2026-02 2026-01

它存在的理由：日常爬取用的 L6M 端點是一個固定 124 個營業日的滾動視窗，進一天、
出一天。成交日一旦滾出視窗就再也換算不了，那筆成交會永久待審（ADR-0018）。
月份端點沒有這個限制，可以把那些日期補回來。

寫入是**加法**：匯率一經寫入即固定，已存在的日期不覆寫（ADR-0006）；成交紀錄
只會從待審變成可用，原幣一個位元組都不動。
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from card_collection.config import DEFAULT_DB_PATH, DEFAULT_IMAGES_DIR  # noqa: E402
from card_collection.fx import (  # noqa: E402
    BOT_MONTH_JPY_URL,
    BotRateDownload,
    FxRateError,
    FxRateRepository,
    parse_bot_csv,
)
from card_collection.services import build_services  # noqa: E402


def backfill(months: list[str], db_path: Path = DEFAULT_DB_PATH) -> None:
    now = datetime.now(UTC)
    # 走正式程式的服務組裝，不自己接一份線——組裝規則只能有一個地方說了算。
    services = build_services(
        db_path=db_path, images_dir=DEFAULT_IMAGES_DIR, clock=lambda: now
    )
    rates = FxRateRepository(services.connection)

    for month in months:
        download = BotRateDownload(url=BOT_MONTH_JPY_URL.format(month=month))
        try:
            fetched = parse_bot_csv(download())
        except FxRateError as error:
            # 抓不到就說出來，絕不當成「那個月沒有匯率」。
            print(f"{month}：失敗——{error}")
            continue
        rates.store(fetched, now.isoformat())
        oldest = min(rate.rate_date for rate in fetched)
        newest = max(rate.rate_date for rate in fetched)
        print(f"{month}：{len(fetched)} 個營業日（{oldest} ～ {newest}）已寫入")

    # 只跑換算，不重爬 SNKRDUNK——成交紀錄早就在庫裡了。因此也不開爬取帳本：
    # 這不是一輪爬取，把它記成一輪會讓「上次更新」說謊。
    result = services.market.convert_pending(now)
    print(
        f"換算：待處理 {result['pending']} 筆、完成 {result['converted']} 筆"
        + (f"、匯率來源錯誤：{result['error']}" if result["error"] else "")
    )
    remaining = services.sales.list_quarantined()
    print(f"仍在待審：{len(remaining)} 筆")
    for sale in remaining:
        print(
            f"  {sale['sold_date_jst']}  ¥{sale['price_jpy']:,}  "
            f"{sale['card_name_raw']}｜{sale['quarantine_reason']}"
        )
    services.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法：uv run python scripts/backfill_fx_month.py YYYY-MM [...]")
    backfill(sys.argv[1:])
