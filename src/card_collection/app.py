"""應用程式組裝。"""

import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from .api import router
from .db import connect, create_schema
from .holding_import import HoldingImportService
from .holdings import HoldingRepository
from .images import CardImageError, CardImageStore
from .mapping import MappingService
from .notion_csv import read_card_kinds
from .repository import MappingCandidateRepository
from .snkrdunk import (
    DEFAULT_REQUEST_INTERVAL_SECONDS,
    USER_AGENT,
    SnkrdunkClient,
    SnkrdunkError,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(
    csv_path: Path,
    db_path: Path,
    images_dir: Path,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    request_interval: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        connection = connect(db_path)
        create_schema(connection)
        repository = MappingCandidateRepository(connection)
        repository.seed(read_card_kinds(csv_path))
        holdings = HoldingRepository(connection)
        # 匯入不合格就讓服務起不來。訊息指出是哪一列，改完 CSV 重啟即可——
        # 帶著半份持有品把服務跑起來，比起不來更糟。
        HoldingImportService(holdings, repository).import_once(csv_path)

        http_client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            follow_redirects=True,
            transport=transport,
        )
        app.state.repository = repository
        app.state.holdings = holdings
        app.state.mapping_service = MappingService(
            repository,
            SnkrdunkClient(http_client, sleep=sleep, request_interval=request_interval),
            CardImageStore(images_dir),
        )
        yield
        http_client.close()
        connection.close()

    app = FastAPI(title="Card Collection", lifespan=lifespan)
    app.state.templates = Jinja2Templates(directory=TEMPLATES_DIR)
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
