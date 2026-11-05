"""應用程式組裝。

接線本身住在 `services.py`——web 服務與兩支 CLI 共用同一份組裝規則。這裡只留下
**web 服務專屬的啟動儀式**：卡種列的 seed 與持有品的一次性匯入。
"""

import mimetypes
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api import router
from .heartbeat import Heartbeat
from .holding_import import HoldingImportService
from .images import CardImageError
from .notion_csv import read_card_kinds
from .services import build_services
from .snkrdunk import DEFAULT_REQUEST_INTERVAL_SECONDS, SnkrdunkError

# Windows 上 Python 的 mimetypes 不認得 .webp，StaticFiles 會回 application/octet-stream；
# Chrome 會自己嗅探，Safari 不保證。在建立 StaticFiles 之前先註冊。
mimetypes.add_type("image/webp", ".webp")

TEMPLATES_DIR = Path(__file__).parent / "templates"
# 三頁的樣式從樣板的 inline <style> 移出後住在這裡（ADR-0023）。掛的是本機檔案，
# 不引入任何外部資源，不違反「零外部資源」的原則。
STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    csv_path: Path,
    db_path: Path,
    images_dir: Path,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    request_interval: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    fx_download: Callable[[], bytes] | None = None,
    heartbeat: Heartbeat | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = build_services(
            db_path=db_path,
            images_dir=images_dir,
            transport=transport,
            sleep=sleep,
            request_interval=request_interval,
            clock=clock,
            fx_download=fx_download,
            heartbeat=heartbeat,
        )
        services.cards.seed(read_card_kinds(csv_path))
        # 匯入不合格就讓服務起不來。訊息指出是哪一列，改完 CSV 重啟即可——
        # 帶著半份持有品把服務跑起來，比起不來更糟。
        HoldingImportService(services.holdings, services.cards).import_once(csv_path)

        app.state.repository = services.cards
        app.state.holdings = services.holdings
        app.state.clock = services.clock
        app.state.mapping_service = services.mapping
        # 行情不掛在啟動流程上：SNKRDUNK 或臺銀掛掉不該讓服務起不來。
        app.state.market_service = services.market
        app.state.crawl_runs = services.runs
        yield
        services.close()

    app = FastAPI(title="Card Collection", lifespan=lifespan)
    app.state.templates = Jinja2Templates(directory=TEMPLATES_DIR)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)

    @app.exception_handler(CardImageError)
    async def _card_image_failed(request: Request, error: CardImageError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(error)}
        )

    @app.exception_handler(SnkrdunkError)
    async def _snkrdunk_failed(request: Request, error: SnkrdunkError) -> JSONResponse:
        """SNKRDUNK 出問題時明確報錯，絕不靜默回空清單。"""
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(error)}
        )

    return app
