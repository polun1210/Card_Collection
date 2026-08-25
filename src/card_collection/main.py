"""正式執行的進入點：uv run uvicorn card_collection.main:app --reload"""

from .app import create_app
from .config import DEFAULT_CSV_PATH, DEFAULT_DB_PATH

app = create_app(csv_path=DEFAULT_CSV_PATH, db_path=DEFAULT_DB_PATH)
