import gzip
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from card_collection.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTION_CSV = REPO_ROOT / "data" / "notion-export" / "pokemon_project.csv"
FIXTURES = Path(__file__).parent / "fixtures" / "snkrdunk"


def _slug(keywords: str) -> str:
    return keywords.replace(" ", "_").replace("-", "")


class RecordedSnkrdunk:
    """在 httpx 傳輸層攔截，回放錄下來的真實 SNKRDUNK 回應。

    手捏的假資料在對方改格式時永遠不會紅，所以 fixture 一律是錄的。
    未錄到的搜尋關鍵字，一律回放那份真實的「查無結果」回應。
    """

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.forced_status: int | None = None
        self.raise_network_error = False
        self.strip_card_image = False
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if self.raise_network_error:
            raise httpx.ConnectError("連線中斷", request=request)
        if self.forced_status is not None:
            return httpx.Response(self.forced_status, text="boom")
        if request.url.path == "/search":
            keywords = request.url.params.get("keywords", "")
            path = FIXTURES / f"search_{_slug(keywords)}.html.gz"
            if not path.exists():
                path = FIXTURES / "search_zzzzznonsense.html.gz"
            return httpx.Response(200, text=gzip.decompress(path.read_bytes()).decode())
        if request.url.path.startswith("/v1/apparels/"):
            apparel_id = request.url.path.rsplit("/", 1)[-1]
            path = FIXTURES / f"apparel_{apparel_id}.json"
            if not path.exists():
                return httpx.Response(404, json={"message": "not found"})
            payload = json.loads(path.read_text(encoding="utf-8"))
            if self.strip_card_image:
                # 錄下的回應拿掉卡圖，用來驗證殘缺資料不會被靜默收下。
                payload.pop("primaryMedia", None)
            return httpx.Response(200, json=payload)
        return httpx.Response(404, text="unrecorded")


@pytest.fixture
def notion_csv() -> Path:
    return NOTION_CSV


@pytest.fixture
def snkrdunk() -> RecordedSnkrdunk:
    return RecordedSnkrdunk()


@pytest.fixture
def client(tmp_path: Path, snkrdunk: RecordedSnkrdunk):
    """真實的暫存 SQLite，不模擬；外部 HTTP 在傳輸層回放錄下的回應。"""
    app = create_app(
        csv_path=NOTION_CSV,
        db_path=tmp_path / "card_collection.db",
        transport=httpx.MockTransport(snkrdunk.handler),
        sleep=snkrdunk.sleep,
    )
    with TestClient(app) as test_client:
        yield test_client
