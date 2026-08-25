"""應用程式組裝。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from .api import router
from .db import connect, create_schema
from .notion_csv import read_card_kinds
from .repository import MappingCandidateRepository

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(csv_path: Path, db_path: Path) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        connection = connect(db_path)
        create_schema(connection)
        repository = MappingCandidateRepository(connection)
        repository.seed(read_card_kinds(csv_path))
        app.state.repository = repository
        yield
        connection.close()

    app = FastAPI(title="Card Collection", lifespan=lifespan)
    app.state.templates = Jinja2Templates(directory=TEMPLATES_DIR)
    app.include_router(router)
    return app
