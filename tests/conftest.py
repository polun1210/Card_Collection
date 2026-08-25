from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from card_collection.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTION_CSV = REPO_ROOT / "data" / "notion-export" / "pokemon_project.csv"


@pytest.fixture
def notion_csv() -> Path:
    return NOTION_CSV


@pytest.fixture
def client(tmp_path: Path):
    """真實的暫存 SQLite，不模擬資料庫；斷言一律走 HTTP API。"""
    app = create_app(csv_path=NOTION_CSV, db_path=tmp_path / "card_collection.db")
    with TestClient(app) as test_client:
        yield test_client
