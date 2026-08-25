"""HTTP API 與待確認清單頁面。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from .repository import MappingCandidateRepository

router = APIRouter()


def get_repository(request: Request) -> MappingCandidateRepository:
    return request.app.state.repository


Repository = Annotated[MappingCandidateRepository, Depends(get_repository)]


@router.get("/api/mapping/queue")
def read_queue(
    repository: Repository,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> list[dict]:
    return list(repository.list_pending(limit=limit))


@router.get("/api/mapping/progress")
def read_progress(repository: Repository) -> dict[str, int]:
    return repository.progress()


@router.get("/", response_class=HTMLResponse)
def read_queue_page(request: Request, repository: Repository) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request,
        "queue.html",
        {"rows": repository.list_pending(), "progress": repository.progress()},
    )
