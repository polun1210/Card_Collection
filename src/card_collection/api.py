"""HTTP API 與待確認清單頁面。"""

import csv
import io
from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .holdings import HoldingRepository, summarize
from .images import IMAGE_MEDIA_TYPE, CardImageError
from .mapping import DEFAULT_BATCH_SIZE, MappingService
from .repository import MappingCandidateRepository

router = APIRouter()


def get_repository(request: Request) -> MappingCandidateRepository:
    return request.app.state.repository


def get_mapping_service(request: Request) -> MappingService:
    return request.app.state.mapping_service


def get_holdings(request: Request) -> HoldingRepository:
    return request.app.state.holdings


Repository = Annotated[MappingCandidateRepository, Depends(get_repository)]
Mapping = Annotated[MappingService, Depends(get_mapping_service)]
Holdings = Annotated[HoldingRepository, Depends(get_holdings)]


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
def read_card(apparel_id: int, repository: Repository) -> dict:
    card = repository.find_card(apparel_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="查無此卡種")
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


@router.get("/api/holdings")
def read_holdings(holdings: Holdings) -> list[dict]:
    return list(holdings.list_all())


@router.get("/api/holdings/summary")
def read_holdings_summary(holdings: Holdings) -> dict[str, int]:
    return summarize(holdings.list_all())


@router.get("/api/holdings/imports")
def read_holding_imports(holdings: Holdings) -> list[dict]:
    """這批資料何時、從哪個檔案匯入的。用來對帳。"""
    return list(holdings.list_imports())


@router.get("/api/cards/{apparel_id}/holdings")
def read_card_holdings(
    apparel_id: int, repository: Repository, holdings: Holdings
) -> dict:
    if repository.find_card(apparel_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="查無此卡種")
    rows = holdings.list_for_apparel(apparel_id)
    return {
        "apparel_id": apparel_id,
        "holdings": list(rows),
        "summary": summarize(rows),
    }


@router.get("/holdings", response_class=HTMLResponse)
def read_holdings_page(request: Request, holdings: Holdings) -> HTMLResponse:
    rows = holdings.list_all()
    return request.app.state.templates.TemplateResponse(
        request,
        "holdings.html",
        {
            "kinds": _group_by_kind(rows),
            "summary": summarize(rows),
            "imports": holdings.list_imports(),
        },
    )


def _group_by_kind(rows: Iterable[dict]) -> list[dict]:
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
