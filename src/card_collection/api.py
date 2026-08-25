"""HTTP API 與待確認清單頁面。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from .mapping import DEFAULT_BATCH_SIZE, MappingService
from .repository import MappingCandidateRepository

router = APIRouter()


def get_repository(request: Request) -> MappingCandidateRepository:
    return request.app.state.repository


def get_mapping_service(request: Request) -> MappingService:
    return request.app.state.mapping_service


Repository = Annotated[MappingCandidateRepository, Depends(get_repository)]
Mapping = Annotated[MappingService, Depends(get_mapping_service)]


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
    row = repository.find_pending(mapping_candidate_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="查無此待確認列")
    mapping.fetch_candidates(mapping_candidate_id)
    return repository.with_candidates(row)


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
            "progress": repository.progress(),
        },
    )
