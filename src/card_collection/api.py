"""HTTP API 與待確認清單頁面。"""

import csv
import io
from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .crawl_runs import CrawlRunInProgress, CrawlRunRepository, freshness
from .holdings import HoldingRepository, summarize, with_market_values
from .images import IMAGE_MEDIA_TYPE, CardImageError
from .mapping import DEFAULT_BATCH_SIZE, MappingService
from .market import MarketService
from .repository import MappingCandidateRepository

router = APIRouter()


def get_repository(request: Request) -> MappingCandidateRepository:
    return request.app.state.repository


def get_mapping_service(request: Request) -> MappingService:
    return request.app.state.mapping_service


def get_holdings(request: Request) -> HoldingRepository:
    return request.app.state.holdings


def get_market(request: Request) -> MarketService:
    return request.app.state.market_service


def get_crawl_runs(request: Request) -> CrawlRunRepository:
    return request.app.state.crawl_runs


def get_clock(request: Request):
    return request.app.state.clock


Repository = Annotated[MappingCandidateRepository, Depends(get_repository)]
Mapping = Annotated[MappingService, Depends(get_mapping_service)]
Holdings = Annotated[HoldingRepository, Depends(get_holdings)]
Market = Annotated[MarketService, Depends(get_market)]
CrawlRuns = Annotated[CrawlRunRepository, Depends(get_crawl_runs)]
Clock = Annotated[object, Depends(get_clock)]


def get_card(apparel_id: int, repository: Repository) -> dict:
    card = repository.find_card(apparel_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="查無此卡種")
    return card


CardRow = Annotated[dict, Depends(get_card)]


EXPORT_COLUMNS = (
    "series_raw",
    "number_raw",
    "card_name_raw",
    "apparel_id",
    "product_catalog_id",
    "card_code",
    "name_en",
    "name_ja",
    "image_local_path",
)


class ConfirmRequest(BaseModel):
    mapping_candidate_id: int
    apparel_id: int


class RejectRequest(BaseModel):
    mapping_candidate_id: int


def _require_pending(repository: MappingCandidateRepository, row_id: int) -> dict:
    row = repository.find_pending(row_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="查無此待確認列"
        )
    return row


@router.get("/api/mapping/queue")
def read_queue(
    repository: Repository,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> list[dict]:
    """純讀取，不打外部。候選由 /api/mapping/candidates/{id} 取回後留存。"""
    return list(repository.list_pending(limit=limit))


@router.post("/api/mapping/candidates/{mapping_candidate_id}")
def fetch_candidates(
    mapping_candidate_id: int, repository: Repository, mapping: Mapping
) -> dict:
    row = _require_pending(repository, mapping_candidate_id)
    mapping.fetch_candidates(mapping_candidate_id)
    return repository.with_candidates(row)


@router.post("/api/mapping/confirm")
def confirm(body: ConfirmRequest, repository: Repository, mapping: Mapping) -> dict:
    row = _require_pending(repository, body.mapping_candidate_id)
    mapping.confirm(row, body.apparel_id)
    return repository.find_card(body.apparel_id)


@router.post("/api/mapping/reject")
def reject(body: RejectRequest, repository: Repository) -> dict[str, int]:
    _require_pending(repository, body.mapping_candidate_id)
    repository.reject(body.mapping_candidate_id)
    return repository.progress()


@router.delete("/api/mapping/confirm/{mapping_candidate_id}")
def undo_confirm(mapping_candidate_id: int, repository: Repository) -> dict[str, int]:
    if not repository.undo_confirm(mapping_candidate_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="這一列沒有已確認的卡種"
        )
    return repository.progress()


@router.get("/api/cards/{apparel_id}")
def read_card(card: CardRow) -> dict:
    return card


@router.post("/api/cards/{apparel_id}/image")
def store_card_image(apparel_id: int, mapping: Mapping) -> dict:
    """補抓確認當下沒拉到的卡圖。不需要推翻確認。"""
    return {"image_local_path": mapping.store_card_image(apparel_id)}


@router.get("/api/cards/{apparel_id}/image")
def read_card_image(apparel_id: int, repository: Repository) -> FileResponse:
    card = repository.find_card(apparel_id)
    if card is None or not card["image_local_path"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="查無卡圖")
    return FileResponse(card["image_local_path"], media_type=IMAGE_MEDIA_TYPE)


@router.get("/api/mapping/export.csv", response_class=PlainTextResponse)
def export_mapping(repository: Repository) -> PlainTextResponse:
    """可離線核對的對照清單。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for card in repository.list_cards():
        writer.writerow([card[column] for column in EXPORT_COLUMNS])
    return PlainTextResponse(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="card-mapping.csv"'},
    )


@router.get("/api/mapping/progress")
def read_progress(repository: Repository) -> dict[str, int]:
    return repository.progress()


# --- 行情 ---------------------------------------------------------------


@router.post("/api/market/crawl")
def crawl_market(market: Market) -> dict:
    """手動觸發一輪全量爬取。日常由排程的 CLI 跑，這裡是補救路徑。

    **維持同步**，不改成 202 ＋ 輪詢：同步端點跑在 threadpool 裡，客戶端斷線不會
    中止它——爬取照樣跑完、資料照樣入庫，唯一的損失是看不到那份報告，而帳本正好
    補上這一塊，重新整理即可看到真實狀態（ADR-0019）。
    """
    try:
        return market.crawl()
    except CrawlRunInProgress as error:
        # 409 而不是 200：這個請求什麼都沒做，說成成功就是說謊。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "run_id": error.run_id},
        ) from error


@router.get("/api/market/runs/latest")
def read_latest_run(runs: CrawlRuns, clock: Clock) -> dict:
    """最近一輪的狀態與統計，外加「是否已過期」的判定。"""
    return freshness(runs.latest(), runs.last_succeeded(), clock())


@router.get("/api/market/runs")
def read_runs(
    runs: CrawlRuns, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[dict]:
    return list(runs.list_recent(limit))


@router.get("/api/market/values")
def read_market_values(market: Market, repository: Repository) -> list[dict]:
    values = market.values()
    return [
        {**_card_identity(card), "market_value": values[card["apparel_id"]]}
        for card in repository.list_cards()
        if card["apparel_id"] in values
    ]


@router.get("/api/market/quarantine")
def read_market_quarantine(market: Market) -> list[dict]:
    """被擋下來的成交與各自的原因。可疑資料不參與計算，但也不會被靜默丟掉。"""
    return list(market.quarantined())


@router.get("/api/cards/{apparel_id}/market")
def read_card_market_value(card: CardRow, market: Market) -> dict:
    """從未抓到任何成交的卡種不給市值——不為了填滿版面而編一個數字。"""
    return {
        **_card_identity(card),
        "market_value": market.value_for(card["apparel_id"]),
    }


@router.get("/api/cards/{apparel_id}/sales")
def read_card_sales(card: CardRow, market: Market) -> list[dict]:
    """單一卡種的成交明細。**稽核用途**，不是給儀表板顯示的。

    原幣、SNKRDUNK 的原始狀態與枚数文字、實際採用的匯率與牌告日都在這裡，
    日後發現換算有誤時回得去，也核對得出篩選是否正確。
    """
    return list(market.sales_for(card["apparel_id"]))


def _card_identity(card: dict) -> dict:
    return {
        "apparel_id": card["apparel_id"],
        "series_raw": card["series_raw"],
        "number_raw": card["number_raw"],
        "card_name_raw": card["card_name_raw"],
    }


# --- 持有品 -------------------------------------------------------------


@router.get("/api/holdings")
def read_holdings(holdings: Holdings, market: Market) -> list[dict]:
    return list(with_market_values(holdings.list_all(), market.values()))


@router.get("/api/holdings/summary")
def read_holdings_summary(holdings: Holdings, market: Market) -> dict[str, int]:
    return summarize(with_market_values(holdings.list_all(), market.values()))


@router.get("/api/holdings/imports")
def read_holding_imports(holdings: Holdings) -> list[dict]:
    """這批資料何時、從哪個檔案匯入的。用來對帳。"""
    return list(holdings.list_imports())


@router.get("/api/cards/{apparel_id}/holdings")
def read_card_holdings(card: CardRow, holdings: Holdings, market: Market) -> dict:
    apparel_id = card["apparel_id"]
    rows = with_market_values(holdings.list_for_apparel(apparel_id), market.values())
    return {
        "apparel_id": apparel_id,
        "holdings": list(rows),
        "summary": summarize(rows),
        "market_value": market.value_for(apparel_id),
    }


@router.get("/holdings", response_class=HTMLResponse)
def read_holdings_page(
    request: Request, holdings: Holdings, market: Market, runs: CrawlRuns, clock: Clock
) -> HTMLResponse:
    values = market.values()
    rows = with_market_values(holdings.list_all(), values)
    return request.app.state.templates.TemplateResponse(
        request,
        "holdings.html",
        {
            "kinds": _group_by_kind(rows, values),
            "summary": summarize(rows),
            "quarantined": market.quarantined(),
            "imports": holdings.list_imports(),
            # 市值有多新，必須與市值本身出現在同一個畫面上。停擺的爬取若不出聲，
            # 三週前的數字看起來與今天的數字一模一樣。
            "freshness": freshness(runs.latest(), runs.last_succeeded(), clock()),
        },
    )


def _group_by_kind(rows: Iterable[dict], values: dict[int, dict]) -> list[dict]:
    """依卡種分組。清單本身已排序，所以同卡種的列必定相鄰。"""
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["series_raw"], row["number_raw"], row["card_name_raw"])
        kind = grouped.setdefault(
            key,
            {
                "series_raw": row["series_raw"],
                "number_raw": row["number_raw"],
                "card_name_raw": row["card_name_raw"],
                "apparel_id": row["apparel_id"],
                "holdings": [],
            },
        )
        kind["holdings"].append(row)
    for kind in grouped.values():
        kind["summary"] = summarize(kind["holdings"])
        kind["market_value"] = values.get(kind["apparel_id"])
    return list(grouped.values())


@router.get("/", response_class=HTMLResponse)
def read_queue_page(
    request: Request,
    repository: Repository,
    mapping: Mapping,
    limit: Annotated[int, Query(ge=1)] = DEFAULT_BATCH_SIZE,
) -> HTMLResponse:
    mapping.ensure_candidates(limit)
    return request.app.state.templates.TemplateResponse(
        request,
        "queue.html",
        {
            "rows": repository.list_pending(limit=limit),
            "cards": repository.list_cards(),
            "progress": repository.progress(),
        },
    )
