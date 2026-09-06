"""HTTP API 與待確認清單頁面。"""

import csv
import io
from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .card_wall import card_wall
from .crawl_runs import CrawlRunInProgress, CrawlRunRepository, freshness
from .holding_rules import HoldingFields, HoldingRuleError, merge, validate
from .holdings import (
    DEFAULT_GRADING,
    HoldingRepository,
    summarize,
    with_market_values,
)
from .images import IMAGE_MEDIA_TYPE, CardImageError
from .indicators import liquidity
from .mapping import DEFAULT_BATCH_SIZE, MappingService
from .market import MarketService
from .portfolio import overview
from .repository import CardKindExists, MappingCandidateRepository
from .snkrdunk import SnkrdunkError
from .trend import daily_trend, spans_a_year

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
        # 動能與流動性掛在這裡而不是自己開一個端點：展開卡片時本來就要打這一支，
        # 多一個接縫等於多一次往返，也多一個之後要一起改的地方。
        "momentum": market.momentum_for(apparel_id),
        "liquidity": liquidity(),
    }


class HoldingCreateRequest(BaseModel):
    mapping_candidate_id: int
    cost_twd: int
    # 省略時為今天。絕大多數情況是當天記帳，但補登昨天的交易也必須做得到。
    purchase_date: str | None = None
    grading_raw: str = DEFAULT_GRADING


class HoldingPatchRequest(BaseModel):
    """部分更新。沒送出的欄位沿用舊值，**明確送出 null 就是清空**。

    分得出這兩者是把誤標的售出改回持有中的唯一辦法。
    """

    mapping_candidate_id: int | None = None
    purchase_date: str | None = None
    cost_twd: int | None = None
    sold_date: str | None = None
    sold_price_twd: int | None = None


class SaleRequest(BaseModel):
    sold_price_twd: int
    sold_date: str | None = None


class CardKindRequest(BaseModel):
    series_raw: str
    number_raw: str
    card_name_raw: str


def _require_holding(holdings: HoldingRepository, holding_id: int) -> dict:
    holding = holdings.find(holding_id)
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="查無此持有品"
        )
    return holding


def _require_kind(repository: MappingCandidateRepository, row_id: int) -> dict:
    kind = repository.find_kind(row_id)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="查無此卡種列"
        )
    return kind


def _validated(merged: dict, today) -> HoldingFields:
    """規則不合格是使用者的輸入問題，回 400 並照實說出是哪個欄位、為什麼。"""
    try:
        return validate(
            merged["purchase_date_raw"],
            merged["cost_twd"],
            merged["sold_date_raw"],
            merged["sold_price_twd"],
            today,
        )
    except HoldingRuleError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error


@router.post("/api/holdings")
def create_holding(
    body: HoldingCreateRequest,
    holdings: Holdings,
    repository: Repository,
    clock: Clock,
) -> dict:
    """手動記一筆購入。持有品掛在卡種列上（ADR-0012），卡種不存在就不收。"""
    _require_kind(repository, body.mapping_candidate_id)
    now = clock()
    fields = _validated(
        {
            "purchase_date_raw": body.purchase_date or now.date().isoformat(),
            "cost_twd": body.cost_twd,
            "sold_date_raw": None,
            "sold_price_twd": None,
        },
        now.date(),
    )
    holding_id = holdings.add(
        body.mapping_candidate_id, fields, now, body.grading_raw
    )
    return holdings.find(holding_id)


@router.patch("/api/holdings/{holding_id}")
def update_holding(
    holding_id: int,
    body: HoldingPatchRequest,
    holdings: Holdings,
    repository: Repository,
    clock: Clock,
) -> dict:
    """驗證的一律是**合併後的完整結果**，否則部分更新就成了繞過規則的後門。"""
    existing = _require_holding(holdings, holding_id)
    changes = body.model_dump(exclude_unset=True)
    kind_id = changes.pop("mapping_candidate_id", None) or existing[
        "mapping_candidate_id"
    ]
    _require_kind(repository, kind_id)
    fields = _validated(merge(existing, changes), clock().date())
    holdings.update(holding_id, kind_id, fields)
    return holdings.find(holding_id)


@router.post("/api/holdings/{holding_id}/sale")
def sell_holding(
    holding_id: int, body: SaleRequest, holdings: Holdings, clock: Clock
) -> dict:
    """賣掉哪一張由使用者指定（ADR-0009），系統不自動挑。

    已售出者回 409：覆蓋掉原本的售出紀錄等於安靜地改寫已實現損益。
    """
    existing = _require_holding(holdings, holding_id)
    if existing["sold_date"] is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="這筆持有品已經售出"
        )
    now = clock()
    fields = _validated(
        merge(
            existing,
            {
                "sold_date": body.sold_date or now.date().isoformat(),
                "sold_price_twd": body.sold_price_twd,
            },
        ),
        now.date(),
    )
    holdings.update(holding_id, existing["mapping_candidate_id"], fields)
    return holdings.find(holding_id)


@router.delete("/api/holdings/{holding_id}")
def delete_holding(holding_id: int, holdings: Holdings) -> dict[str, int]:
    _require_holding(holdings, holding_id)
    holdings.delete(holding_id)
    return {"deleted": holding_id}


@router.post("/api/card-kinds")
def create_card_kind(body: CardKindRequest, repository: Repository) -> dict:
    """新增的卡種進入待確認清單，沿用既有的搜尋 → 確認 → 抓卡圖流程。"""
    try:
        row_id = repository.add_kind(
            body.series_raw, body.number_raw, body.card_name_raw
        )
    except CardKindExists as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"id": error.existing_id, "message": str(error)},
        ) from error
    return repository.find_kind(row_id)


@router.get("/api/portfolio")
def read_portfolio(
    holdings: Holdings, market: Market, runs: CrawlRuns, clock: Clock
) -> dict:
    """首頁要的一切，一次拿齊，畫面不必自己去湊四個地方。

    走勢圖的資料**一次全給**：`7D / 1M / 3M / YTD / ALL` 之中 ALL 是其他四個的
    超集合，在瀏覽器切片即可。這省掉一個端點，也讓區間切換是零延遲的。
    """
    rows = with_market_values(holdings.list_all(), market.values())
    return {
        "summary": overview(summarize(rows)),
        "trend": daily_trend(rows, market.active_sales(), market.today()),
        "freshness": freshness(runs.latest(), runs.last_succeeded(), clock()),
        "wall": card_wall(rows),
    }


@router.get("/", response_class=HTMLResponse)
def read_portfolio_page(
    request: Request,
    holdings: Holdings,
    market: Market,
    runs: CrawlRuns,
    clock: Clock,
    repository: Repository,
) -> HTMLResponse:
    """打開就看到自己的收藏，不是後台工具——待審佇列因此在 /queue。"""
    portfolio = read_portfolio(holdings, market, runs, clock)
    return request.app.state.templates.TemplateResponse(
        request,
        "portfolio.html",
        {
            **portfolio,
            "active_page": "portfolio",
            # 跨度不足一年時，YTD 會是一個與 ALL 完全一樣的區間，不給它按鈕。
            "show_ytd": spans_a_year(portfolio["trend"]),
            # 流動性對每一個卡種都一樣，由伺服器渲染即可——它不必等腳本跑完，
            # 理由也就只有 indicators.py 一個地方說了算。
            "liquidity": liquidity(),
            # 新增持有品要從全部卡種裡挑一個，不只是已經有持有品的那些。
            "all_kinds": repository.list_kinds(),
            "today": clock().date().isoformat(),
        },
    )


@router.get("/holdings", response_class=HTMLResponse)
def read_holdings_page(
    request: Request,
    holdings: Holdings,
    market: Market,
    runs: CrawlRuns,
    clock: Clock,
    repository: Repository,
) -> HTMLResponse:
    values = market.values()
    rows = with_market_values(holdings.list_all(), values)
    return request.app.state.templates.TemplateResponse(
        request,
        "holdings.html",
        {
            "active_page": "holdings",
            "kinds": _group_by_kind(rows, values),
            # 新增持有品要從全部卡種裡挑一個，不只是已經有持有品的那些。
            "all_kinds": repository.list_kinds(),
            "today": clock().date().isoformat(),
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


@router.get("/queue", response_class=HTMLResponse)
def read_queue_page(
    request: Request,
    repository: Repository,
    mapping: Mapping,
    limit: Annotated[int, Query(ge=1)] = DEFAULT_BATCH_SIZE,
) -> HTMLResponse:
    try:
        mapping.ensure_candidates(limit)
    except SnkrdunkError:
        # 來源掛掉不該讓整頁 500——待處理清單與歷史都還讀得出來（這是真實發生過的
        # 當機）。抓不到候選的那幾列 candidates_fetched_at 仍是 NULL，樣板呈現成
        # 「無法取得 SNKRDUNK 候選」並提供重試（spec §10.8）。ensure_candidates 的
        # 迴圈在第一列失敗時就中止，其後的列根本沒被嘗試、同樣是 NULL、同樣顯示
        # 那個狀態——語意上可接受（確實沒取得），但不代表「這一列試過且失敗」。
        pass
    return request.app.state.templates.TemplateResponse(
        request,
        "queue.html",
        {
            "active_page": "queue",
            "rows": repository.list_pending(limit=limit),
            "cards": repository.list_cards(),
            # 被「不納入行情」的卡種（status == rejected）。list_unconfirmed() 回的是
            # pending + rejected，這裡只留 rejected 給歷史的「不納入行情」分頁（spec §10.11）。
            "rejected": [
                row
                for row in repository.list_unconfirmed()
                if row["status"] == "rejected"
            ],
            "progress": repository.progress(),
        },
    )
