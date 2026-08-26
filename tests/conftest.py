import csv
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from card_collection.app import create_app
from card_collection.fx import BOT_L6M_JPY_URL, FxRateError

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTION_CSV = REPO_ROOT / "data" / "notion-export" / "pokemon_project.csv"
FIXTURES = Path(__file__).parent / "fixtures" / "snkrdunk"
FX_FIXTURES = Path(__file__).parent / "fixtures" / "fx"

# fixture 錄於 2026-08-25。測試裡的「今天」必須固定，否則「近 30 天有成交」
# 這件事會隨著真實時間流逝自己變成假的——那種測試只會在某個週一莫名其妙變紅。
DEFAULT_NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _slug(keywords: str) -> str:
    return keywords.replace(" ", "_").replace("-", "")


def _recorded(path: Path) -> bytes | None:
    """大的回應錄成 .gz，小的直接存。取用時兩種都認。"""
    if path.exists():
        return path.read_bytes()
    compressed = path.with_suffix(path.suffix + ".gz")
    if compressed.exists():
        return gzip.decompress(compressed.read_bytes())
    return None


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
        self.strip_product_catalog_id = False
        self.image_download_fails = False
        self.image_is_corrupt = False
        self.trading_fails_for: set[int] = set()
        self.variant_filter_ignored = False
        self.sleeps: list[float] = []
        self._image_owner: dict[str, int] | None = None

    @property
    def image_owner(self) -> dict[str, int]:
        """卡圖網址 → apparel id，由錄下的卡種回應反查。"""
        if self._image_owner is None:
            self._image_owner = {}
            for path in FIXTURES.glob("apparel_*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                media = payload.get("primaryMedia") or {}
                if media.get("imageUrl"):
                    self._image_owner[media["imageUrl"]] = payload["id"]
        return self._image_owner

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if self.raise_network_error:
            raise httpx.ConnectError("連線中斷", request=request)
        if self.forced_status is not None:
            return httpx.Response(self.forced_status, text="boom")
        if request.url.host == "cdn.snkrdunk.com":
            if self.image_download_fails:
                return httpx.Response(503, text="cdn down")
            if self.image_is_corrupt:
                return httpx.Response(200, content=b"not an image at all")
            apparel_id = self.image_owner.get(str(request.url))
            path = FIXTURES / f"image_{apparel_id}.webp"
            if apparel_id is None or not path.exists():
                return httpx.Response(404, text="unrecorded image")
            return httpx.Response(
                200, content=path.read_bytes(), headers={"Content-Type": "image/webp"}
            )
        if request.url.path == "/search":
            keywords = request.url.params.get("keywords", "")
            path = FIXTURES / f"search_{_slug(keywords)}.html.gz"
            if not path.exists():
                path = FIXTURES / "search_zzzzznonsense.html.gz"
            return httpx.Response(200, text=gzip.decompress(path.read_bytes()).decode())
        if request.url.path.startswith("/v3/products/"):
            return self._trading_history(request)
        if request.url.path.startswith("/v1/apparels/"):
            apparel_id = request.url.path.rsplit("/", 1)[-1]
            path = FIXTURES / f"apparel_{apparel_id}.json"
            if not path.exists():
                return httpx.Response(404, json={"message": "not found"})
            payload = json.loads(path.read_text(encoding="utf-8"))
            if self.strip_card_image:
                # 錄下的回應拿掉卡圖，用來驗證殘缺資料不會被靜默收下。
                payload.pop("primaryMedia", None)
            if self.strip_product_catalog_id:
                payload.pop("productCatalogId", None)
            return httpx.Response(200, json=payload)
        return httpx.Response(404, text="unrecorded")

    def _trading_history(self, request: httpx.Request) -> httpx.Response:
        product_catalog_id = int(request.url.path.split("/")[3])
        if product_catalog_id in self.trading_fails_for:
            return httpx.Response(500, text="boom")
        variant_id = request.url.params.get("variant_id")
        if self.variant_filter_ignored:
            # 模擬來源端的枚数篩選失效：照樣回未篩選的那份，多張一組會混進來。
            variant_id = None
        name = f"trading_{product_catalog_id}"
        if variant_id:
            name += f"_variant_{variant_id}"
        body = _recorded(FIXTURES / f"{name}.json")
        if body is None:
            return httpx.Response(404, text="unrecorded trading history")
        return httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )


# 錄製時實際收到的機器人驗證頁開頭，逐字取自 tests/fixtures/RECORDING-REPORT.md。
# 當時那份回應沒有留成 fixture 檔——留著會讓 fixture 目錄看起來像有四個可用的
# 匯率來源（見該報告）。這裡放的是它留下的紀錄，不是手捏的假資料。
def _to_english(body: bytes) -> bytes:
    """把錄下的中文牌告換成英文版的字樣。

    實測 curl_cffi 模擬 Chrome 時會連 `Accept-Language: en-US` 一起送，臺銀就回
    英文版：欄位位置與數值完全相同，只有方向欄從「本行買入」變成「Buying」。
    """
    text = body.decode("utf-8-sig")
    text = text.replace("本行買入", "Buying").replace("本行賣出", "Selling")
    return text.encode("utf-8-sig")


BOT_CHALLENGE_PAGE = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1, '
    'shrink-to-fit=no"><title>Challenge Validation</title><link rel="styleshee'
)


class RecordedFx:
    """回放錄下來的臺銀牌告回應。

    它是一個**下載器**而不是 httpx handler：正式程式走 curl_cffi 模擬 Chrome 的
    TLS 指紋（ADR-0017），那是另一套 HTTP 堆疊，攔不到 httpx 的傳輸層。

    幾種失敗各自不同，測試要分得出來：

    - `bot_challenge`：機器人驗證頁。狀態 200，只有內容看得出來。
    - `wrong_shape`：今日全幣別牌告（真實錄到的回應）。合法 CSV，但沒有日圓的歷史牌告。
    - `english`：英文版牌告（真實回應的形狀）。方向欄是 Buying 而不是本行買入。
    - `fails_with`：連不上或非 200，帶著下載器會丟出的訊息。
    """

    # 打錯字的旗標要當場炸掉。少了它，`fx.blocked = True` 這種筆誤會靜默失效，
    # 測試照樣綠——那是最糟的一種綠。
    __slots__ = (
        "requests",
        "bot_challenge",
        "wrong_shape",
        "english",
        "fails_with",
        "published_through",
    )

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.bot_challenge = False
        self.wrong_shape = False
        self.english = False
        self.fails_with: str | None = None
        # 只掛到某一天為止（格式 YYYYMMDD）：模擬當日牌告還沒掛出來。
        self.published_through: str | None = None

    def __call__(self) -> bytes:
        self.requests.append(BOT_L6M_JPY_URL)
        if self.fails_with is not None:
            raise FxRateError(self.fails_with)
        if self.bot_challenge:
            return BOT_CHALLENGE_PAGE.encode("utf-8")
        name = "bot_today_all_csv" if self.wrong_shape else "bot_jpy_l6m_csv_upper"
        body = self._truncate(_recorded(FX_FIXTURES / f"{name}.txt"))
        return _to_english(body) if self.english else body

    def _truncate(self, body: bytes) -> bytes:
        """砍掉比 published_through 更新的那幾列，其餘逐字保留。"""
        if self.published_through is None:
            return body
        text = body.decode("utf-8-sig")
        kept = [
            line
            for line in text.splitlines(keepends=True)
            if line[:8] <= self.published_through or not line[:8].isdigit()
        ]
        return "".join(kept).encode("utf-8-sig")


@pytest.fixture
def notion_csv() -> Path:
    return NOTION_CSV


@pytest.fixture
def snkrdunk() -> RecordedSnkrdunk:
    return RecordedSnkrdunk()


@pytest.fixture
def fx() -> RecordedFx:
    return RecordedFx()


@pytest.fixture
def client_factory(tmp_path: Path, snkrdunk: RecordedSnkrdunk, fx: RecordedFx):
    """同一組暫存資料庫與卡圖目錄，可重複建立 app——用來驗證重啟後的狀態。

    可指定自己的 CSV（驗證不合格來源資料的匯入），也可指定「現在」是何時
    （驗證市值過期與否）。
    """

    def make(csv_path: Path = NOTION_CSV, now: datetime = DEFAULT_NOW) -> TestClient:
        app = create_app(
            csv_path=csv_path,
            db_path=tmp_path / "card_collection.db",
            images_dir=tmp_path / "images",
            transport=httpx.MockTransport(snkrdunk.handler),
            sleep=snkrdunk.sleep,
            clock=lambda: now,
            fx_download=fx,
        )
        return TestClient(app)

    return make


# 卡種列 →（apparel id, productCatalogId）。fixture 只錄了八個 apparel，湊不齊 68 個
# 卡種，因此這裡的配對依據是**錄下來的成交紀錄形狀**，不是真實世界的卡種對應。
LUCARIO = ("M2a", "228", "MEGA Lucario", 722241, 834208)
PRINTING_ERROR = ("M2a", "228", "MEGA Lucario Printing Error", 744296, 859607)
PIKACHU_25TH = ("S8a", "1", "Pikachu 25th", 141410, 217570)
OLD_TRADES = ("S-P", "144", "Pikachu", 91103, 167274)
BEFORE_FX_RANGE = ("S-P", "323", "Pikachu", 95803, 171973)


@pytest.fixture
def confirm_card():
    """把某個卡種列確認到指定的 apparel，之後行情才抓得動它。"""

    def confirm(client: TestClient, card: tuple) -> int:
        series, number, card_name, apparel_id = card[:4]
        row = next(
            row
            for row in client.get("/api/mapping/queue").json()
            if (row["series_raw"], row["number_raw"], row["card_name_raw"])
            == (series, number, card_name)
        )
        response = client.post(
            "/api/mapping/confirm",
            json={"mapping_candidate_id": row["id"], "apparel_id": apparel_id},
        )
        assert response.status_code == 200, response.text
        return row["id"]

    return confirm


@pytest.fixture
def crawl():
    def run(client: TestClient) -> dict:
        response = client.post("/api/market/crawl")
        assert response.status_code == 200, response.text
        return response.json()

    return run


NOTION_COLUMNS = (
    "card name",
    "card num",
    "cost",
    "grading score",
    "purchase date",
    "set name",
    "sold date",
    "sold price",
)


@pytest.fixture
def write_notion_csv(tmp_path: Path):
    """寫一份欄位與 Notion 匯出相同的 CSV，只是內容由測試指定。"""

    def write(*holdings: dict[str, str]) -> Path:
        path = tmp_path / "custom.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=NOTION_COLUMNS)
            writer.writeheader()
            for holding in holdings:
                writer.writerow({column: "" for column in NOTION_COLUMNS} | holding)
        return path

    return write


@pytest.fixture
def client(client_factory):
    """真實的暫存 SQLite，不模擬；外部 HTTP 在傳輸層回放錄下的回應。"""
    with client_factory() as test_client:
        yield test_client
