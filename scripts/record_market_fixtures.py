"""一次性 fixture 錄製腳本：成交紀錄與匯率（issue #8）。

**這支腳本會對外發送網路請求**，請自行執行，不要交給自動化流程跑：

    uv run python scripts/record_market_fixtures.py

它做兩件事：

1. 為既有 apparel fixture 對應的卡種錄下 SNKRDUNK 的成交紀錄回應。
2. 逐一探測候選的匯率來源，回報各自回了什麼——**不預設哪一個可用**。

錄下的檔案進 `tests/fixtures/`，另外產出一份 `RECORDING-REPORT.md`，
用來回答 issue #8 裡「匯率來源要選哪一個」的待驗證問題。

對外請求一律序列化並固定間隔，與正式程式碼採同一組設定。
"""

import gzip
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from card_collection.snkrdunk import (  # noqa: E402
    BASE_URL,
    DEFAULT_REQUEST_INTERVAL_SECONDS,
    USER_AGENT,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures"
SNKRDUNK_FIXTURES = FIXTURES / "snkrdunk"
FX_FIXTURES = FIXTURES / "fx"
REPORT_PATH = FIXTURES / "RECORDING-REPORT.md"

PSA10_CONDITION = "trading_card_single_psa10"
COMPRESS_ABOVE_BYTES = 20_000

# 候選匯率來源。**全部未經驗證**——這支腳本的工作就是問出誰能用。
# 要回答的問題：哪一個直接提供 JPY→TWD、哪一個只給美元而需走交叉匯率、
# 歷史能回溯多久、週末假日缺不缺值。
FX_CANDIDATES = (
    (
        "bot_jpy_l6m_html",
        "https://rate.bot.com.tw/xrt/quote/l6m/JPY",
        "臺銀｜日圓近六個月牌告 HTML（**已實測可用**：124 個營業日、含現金與即期）",
    ),
    (
        "bot_jpy_l6m_csv_upper",
        "https://rate.bot.com.tw/xrt/flcsv/0/L6M/JPY",
        "臺銀｜日圓近六個月牌告 CSV，大寫路徑（小寫版回「找不到資料」）",
    ),
    (
        "bot_today_all_csv",
        "https://rate.bot.com.tw/xrt/flcsv/0/day",
        "臺銀｜今日全幣別牌告 CSV（實測回機器人驗證頁）",
    ),
    (
        "cbc_exchange_rate_index",
        "https://www.cbc.gov.tw/tw/lp-644-1.html",
        "央行｜匯率專區入口（實測回的是外匯存底頁）",
    ),
    (
        "cbc_usd_closing",
        "https://www.cbc.gov.tw/tw/np-1053-1.html",
        "央行｜新臺幣對美元銀行間收盤匯率（實測回轉址 stub）",
    ),
)

# 200 不等於成功。這些內容出現在回應裡，代表這個來源實際上沒給我們資料——
# 這正是本專案最在意的「安靜說謊」：狀態碼漂亮，內容是空的。
NOT_ACTUALLY_DATA = (
    ("找不到任何一筆資料", "查詢無資料"),
    ("Challenge Validation", "被機器人驗證擋下"),
    ("sec-text-container", "被機器人驗證擋下"),
    ("location.href=", "只是轉址 stub，沒有內容"),
    ("外匯存底", "回的是外匯存底頁，不是匯率頁"),
)


@dataclass
class Probe:
    """一次對外請求的結果。失敗也記下來——沒回應本身就是答案。"""

    name: str
    url: str
    note: str
    status: int | None = None
    content_type: str = ""
    size: int = 0
    saved_as: str = ""
    error: str = ""
    usable: bool = True
    findings: list[str] = field(default_factory=list)


class Recorder:
    """序列化的對外請求，每次之間固定間隔。與正式客戶端同一組設定。"""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self._has_requested = False

    def get(self, url: str, **kwargs) -> httpx.Response:
        import time

        if self._has_requested:
            time.sleep(DEFAULT_REQUEST_INTERVAL_SECONDS)
        self._has_requested = True
        return self._client.get(url, **kwargs)


def save(path: Path, body: bytes) -> str:
    """大的回應壓縮存檔，與既有 search_*.html.gz 的作法一致。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(body) > COMPRESS_ABOVE_BYTES:
        path = path.with_suffix(path.suffix + ".gz")
        path.write_bytes(gzip.compress(body))
    else:
        path.write_bytes(body)
    return path.name


# --- SNKRDUNK 成交紀錄 ---------------------------------------------------


def known_cards() -> list[tuple[int, int, str]]:
    """從既有的 apparel fixture 反查卡種——測試能確認的就是這幾張。"""
    cards = []
    for path in sorted(SNKRDUNK_FIXTURES.glob("apparel_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        product_catalog_id = payload.get("productCatalogId")
        if product_catalog_id:
            cards.append(
                (payload["id"], product_catalog_id, (payload.get("name") or "")[:60])
            )
    return cards


def trading_history_url(product_catalog_id: int, variant_id: int | None = None) -> str:
    """路徑上的 id 是 productCatalogId，不是 apparel id（ADR-0007）。"""
    url = (
        f"{BASE_URL}/v3/products/{product_catalog_id}/trading-history"
        f"?condition_code={PSA10_CONDITION}"
    )
    return url if variant_id is None else f"{url}&variant_id={variant_id}"


def single_card_variant_id(payload: dict) -> tuple[int | None, list[str]]:
    """從 filters.variants.options 找出「1枚」的 id。

    實測結構：filters 是 dict，底下 variants 與 conditions 各自帶 options，
    枚数選項形如 {"id": 2116195, "name": "1枚"}，共 1～10 枚十個選項。
    """
    options = ((payload.get("filters") or {}).get("variants") or {}).get("options") or []
    names = [str(option.get("name") or "") for option in options]
    for option in options:
        if str(option.get("name") or "").replace(" ", "") == "1枚":
            return option.get("id"), names
    return None, names


def describe_trades(payload: dict) -> list[str]:
    """回報這張卡的成交密度——用來挑「近 30 天有／無成交」的測試對象。"""
    trades = payload.get("trades") or []
    if not trades:
        return ["trades 0 筆"]
    sold_dates = sorted(
        str(trade.get("soldAt") or "")[:10] for trade in trades if trade.get("soldAt")
    )
    findings = [f"trades {len(trades)} 筆"]
    if sold_dates:
        findings.append(f"最舊 {sold_dates[0]}、最新 {sold_dates[-1]}")
        newest = datetime.fromisoformat(sold_dates[-1]).replace(tzinfo=UTC)
        stale_days = (datetime.now(UTC) - newest).days
        findings.append(
            f"距今 {stale_days} 天 → {'近 30 天有成交' if stale_days <= 30 else '**近 30 天無成交**'}"
        )
    labels = {str(trade.get("label") or "") for trade in trades}
    findings.append(f"枚数標籤 {sorted(labels)}")
    findings.append(f"狀態標籤 {sorted({str(t.get('title') or '') for t in trades})}")

    # 完全相同的成交（同時間、同價、同枚数）——去重設計的關鍵證據。
    seen: dict[tuple, int] = {}
    for trade in trades:
        key = (trade.get("soldAt"), trade.get("price"), trade.get("label"))
        seen[key] = seen.get(key, 0) + 1
    duplicates = {key: count for key, count in seen.items() if count > 1}
    if duplicates:
        findings.append(
            f"**有 {len(duplicates)} 組完全相同的成交**（最多 {max(duplicates.values())} 筆）"
            "→ 唯一鍵必須含同批次內的重複序號"
        )

    # chart 實測是 dict：{"lines": [{"points": [...]}], "ranges": [...]}
    points = 0
    for line in ((payload.get("chart") or {}).get("lines") or []):
        points += len(line.get("points") or [])
    if points:
        findings.append(f"chart {points} 點（僅供參考，ADR-0007 明令不得寫入資料庫）")
    return findings


def record_trading_history(recorder: Recorder) -> list[Probe]:
    probes = []
    for apparel_id, product_catalog_id, name in known_cards():
        probe = Probe(
            name=f"trading_{product_catalog_id}",
            url=trading_history_url(product_catalog_id),
            note=f"apparel {apparel_id}｜{name}",
        )
        probes.append(probe)
        try:
            response = recorder.get(
                probe.url, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as error:
            probe.error = f"請求失敗：{error}"
            continue
        probe.status = response.status_code
        probe.content_type = response.headers.get("content-type", "")
        probe.size = len(response.content)
        if response.status_code != httpx.codes.OK:
            probe.error = f"非 200：{response.text[:200]}"
            continue
        probe.saved_as = save(
            SNKRDUNK_FIXTURES / f"trading_{product_catalog_id}.json", response.content
        )
        payload = response.json()
        variant_id, labels = single_card_variant_id(payload)
        probe.findings = describe_trades(payload)
        probe.findings.append(f"filters 枚数選項 {labels or '（無）'}")
        if variant_id is None:
            probe.findings.append("**找不到 1 枚選項** → 篩選邏輯需依實際結構調整")
            continue
        probes.append(
            _record_single_variant(recorder, product_catalog_id, variant_id, name)
        )
    return probes


def _record_single_variant(
    recorder: Recorder, product_catalog_id: int, variant_id: int, name: str
) -> Probe:
    """帶 variant_id 再取一次，讓 20 筆上限全部落在單張成交上。"""
    probe = Probe(
        name=f"trading_{product_catalog_id}_variant_{variant_id}",
        url=trading_history_url(product_catalog_id, variant_id),
        note=f"1 枚篩選｜{name}",
    )
    try:
        response = recorder.get(probe.url, headers={"Accept": "application/json"})
    except httpx.HTTPError as error:
        probe.error = f"請求失敗：{error}"
        return probe
    probe.status = response.status_code
    probe.content_type = response.headers.get("content-type", "")
    probe.size = len(response.content)
    if response.status_code != httpx.codes.OK:
        probe.error = f"非 200：{response.text[:200]}"
        return probe
    probe.saved_as = save(
        SNKRDUNK_FIXTURES
        / f"trading_{product_catalog_id}_variant_{variant_id}.json",
        response.content,
    )
    probe.findings = describe_trades(response.json())
    return probe


# --- 匯率來源探測 -------------------------------------------------------


def probe_fx_sources(recorder: Recorder) -> list[Probe]:
    probes = []
    for name, url, note in FX_CANDIDATES:
        probe = Probe(name=name, url=url, note=note)
        probes.append(probe)
        try:
            response = recorder.get(url)
        except httpx.HTTPError as error:
            probe.error = f"請求失敗：{error}"
            continue
        probe.status = response.status_code
        probe.content_type = response.headers.get("content-type", "")
        probe.size = len(response.content)
        if response.status_code != httpx.codes.OK:
            probe.error = f"非 200：{response.text[:200]}"
            continue
        probe.saved_as = save(FX_FIXTURES / f"{name}.txt", response.content)
        probe.findings = _describe_fx(response)
        probe.usable = not any("不可用" in finding for finding in probe.findings)
    return probes


def _describe_fx(response: httpx.Response) -> list[str]:
    """回答關鍵問題：有沒有日圓、是不是只有美元、歷史回溯多久。"""
    text = response.text
    findings = []
    for marker, reason in NOT_ACTUALLY_DATA:
        if marker in text:
            findings.append(f"**狀態 200 但沒有資料：{reason}** → 此來源不可用")
            findings.append(f"前 200 字：{text[:200].strip()!r}")
            return findings
    has_jpy = "JPY" in text or "日圓" in text or "日幣" in text
    has_usd = "USD" in text or "美元" in text or "美金" in text
    findings.append(f"提及日圓：{'是' if has_jpy else '否'}")
    findings.append(f"提及美元：{'是' if has_usd else '否'}")
    if has_usd and not has_jpy:
        findings.append("**只有美元 → JPY→TWD 需走交叉匯率，誤差會疊加**")
    dates = sorted(
        {
            line[:10]
            for line in text.splitlines()
            if len(line) >= 10 and line[:4].isdigit() and line[4] in "-/"
        }
    )
    if dates:
        findings.append(f"看起來的日期範圍：{dates[0]} ～ {dates[-1]}（共 {len(dates)} 個）")
    findings.append(f"前 200 字：{text[:200].strip()!r}")
    return findings


# --- 報告 ---------------------------------------------------------------


def write_report(snkrdunk: list[Probe], fx: list[Probe]) -> None:
    lines = [
        "# fixture 錄製結果（issue #8）",
        "",
        f"錄製時間：{datetime.now(UTC).isoformat()}",
        "",
        "本檔由 `scripts/record_market_fixtures.py` 產生。",
        "用來回答 issue #8 的待驗證問題，決定後請寫成 ADR。",
        "",
        "## 匯率來源探測",
        "",
        "**要回答的問題**：哪一個來源直接提供 JPY→TWD？"
        "若只提供美元，就得走交叉匯率——那是兩次換算的誤差疊加，且不會報錯。",
        "",
    ]
    lines += _probe_section(fx)
    lines += ["", "## SNKRDUNK 成交紀錄", "", _snkrdunk_intro(), ""]
    lines += _probe_section(snkrdunk)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _snkrdunk_intro() -> str:
    return (
        "測試需要兩種卡種各至少一個：**近 30 天有成交**（驗證市值計算）與"
        "**近 30 天無成交**（驗證沿用舊市值並標註過期天數）。"
        "請從下方的「距今幾天」挑選。"
    )


def _probe_section(probes: list[Probe]) -> list[str]:
    lines = []
    for probe in probes:
        lines.append(f"### {probe.name}")
        lines.append("")
        lines.append(f"- 說明：{probe.note}")
        lines.append(f"- 網址：`{probe.url}`")
        if probe.error:
            lines.append(f"- **失敗**：{probe.error}")
        else:
            lines.append(
                f"- 回應：{probe.status}｜{probe.content_type}｜{probe.size:,} bytes"
            )
            lines.append(f"- 存檔：`{probe.saved_as}`")
        for finding in probe.findings:
            lines.append(f"- {finding}")
        lines.append("")
    return lines


def summarize(probes: list[Probe], title: str) -> None:
    """狀態 200 但沒有資料不算成功——那正是本專案最在意的安靜說謊。"""
    usable = [probe for probe in probes if probe.saved_as and probe.usable]
    empty = [probe for probe in probes if probe.saved_as and not probe.usable]
    failed = [probe for probe in probes if not probe.saved_as]
    print(f"\n{title}：可用 {len(usable)}、200 但無資料 {len(empty)}、失敗 {len(failed)}")
    for probe in empty:
        print(f"  ~ {probe.name}｜200 但沒有資料")
    for probe in failed:
        print(f"  x {probe.name}｜{probe.error or '未存檔'}")


def main() -> None:
    skip_fx = "--skip-fx" in sys.argv
    skip_snkrdunk = "--skip-snkrdunk" in sys.argv
    print("開始錄製。所有請求序列化並固定間隔，請勿中途重跑以免對來源造成壓力。\n")
    fx: list[Probe] = []
    snkrdunk: list[Probe] = []
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    ) as client:
        recorder = Recorder(client)
        if skip_fx:
            print("[1/2] 略過匯率來源（--skip-fx）")
        else:
            print("[1/2] 探測匯率來源…")
            fx = probe_fx_sources(recorder)
            summarize(fx, "匯率來源")
        if skip_snkrdunk:
            print("\n[2/2] 略過成交紀錄（--skip-snkrdunk）")
        else:
            print("\n[2/2] 錄製 SNKRDUNK 成交紀錄…")
            snkrdunk = record_trading_history(recorder)
            summarize(snkrdunk, "成交紀錄")
    write_report(snkrdunk, fx)
    print(f"\n報告已寫入：{REPORT_PATH}")
    print("請把報告內容貼回對話，用來定案匯率來源與測試對象。")


if __name__ == "__main__":
    main()
