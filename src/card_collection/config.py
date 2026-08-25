"""預設路徑。測試會覆寫這些值，改用暫存資料庫。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_PATH = REPO_ROOT / "data" / "notion-export" / "pokemon_project.csv"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "card_collection.db"
