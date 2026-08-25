"""HTTP API 與待確認清單頁面。"""

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .images import IMAGE_MEDIA_TYPE, CardImageError
from .mapping import DEFAULT_BATCH_SIZE, MappingService
from .repository import MappingCandidateRepository

router = APIRouter()


def get_repository(request: Request) -> MappingCandidateRepository:
    return request.app.state.repository


def get_mapping_service(request: Request) -> MappingService:
    return request.app.state.mapping_service


Repository = Annotated[MappingCandidateRepository, Depends(get_repository)]
Mapping = Annotated[MappingService, Depends(get_mapping_service)]


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
