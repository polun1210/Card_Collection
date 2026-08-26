"""排程叫得動它嗎——CLI 的結束碼與 log。

**結束碼是 Windows 工作排程器唯一看得到的訊號。** 它若說錯話，排程歷程就會拿「跑完
了但有卡種失敗」當成功、拿「已有一輪在跑」當紅字——兩種都會讓人不再相信那份歷程。

log 檔則是排程跑的時候唯一留得下來的紀錄：那個時間點沒有人在看畫面。
"""

import importlib.util
from pathlib import Path

import httpx
import pytest

from card_collection.crawl_runs import TRIGGER_SCHEDULED
from conftest import DEFAULT_NOW, LUCARIO, PIKACHU_25TH

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    """scripts/ 不是套件，照檔案路徑載進來。"""
    spec = importlib.util.spec_from_file_location(
        "crawl_script", REPO_ROOT / "scripts" / "crawl.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crawl_script = _load_script()


@pytest.fixture
def cli(tmp_path, snkrdunk, fx, heartbeat, client, confirm_card):
    """跑真正的進入點 `main()`，外部回應一律回放錄下來的那份。

    資料庫與 `client` 是同一個檔案——CLI 與 web 服務本來就共用它（ADR-0019）。
    """
    log_dir = tmp_path / "logs"

    def run(*cards, dry_run: bool = False) -> tuple[int, str]:
        for card in cards:
            confirm_card(client, card)
        # 確認卡種時送出的請求是布景，不是這一輪爬取送出的。混在一起會讓
        # 「乾跑不發請求」這個斷言永遠紅著，而且紅的理由是假的。
        snkrdunk.requests.clear()
        code = crawl_script.main(
            dry_run=dry_run,
            db_path=tmp_path / "card_collection.db",
            images_dir=tmp_path / "images",
            log_dir=log_dir,
            transport=httpx.MockTransport(snkrdunk.handler),
            sleep=snkrdunk.sleep,
            clock=lambda: DEFAULT_NOW,
            fx_download=fx,
            heartbeat=heartbeat.build(),
        )
        log_path = log_dir / f"crawl-{DEFAULT_NOW.date().isoformat()}.log"
        return code, log_path.read_text(encoding="utf-8")

    return run


# --- 結束碼 -------------------------------------------------------------


def test_一輪跑完且沒有卡種失敗時結束碼是0(cli):
    code, log = cli(LUCARIO)

    assert code == crawl_script.EXIT_OK
    assert "完成（run 1）" in log


def test_有卡種失敗時結束碼是2(cli, snkrdunk):
    snkrdunk.trading_fails_for = {LUCARIO[4]}

    code, log = cli(LUCARIO, PIKACHU_25TH)

    # 排在 0 與 1 之間：這一輪確實跑完了，但它不乾淨——兩者不能共用一個碼。
    assert code == crawl_script.EXIT_CARDS_FAILED
    assert "卡種失敗：M2a #228 MEGA Lucario" in log


def test_整輪失敗時結束碼是1(cli, fx):
    fx.crashes_with = "匯率下載器整個炸了"

    code, log = cli(LUCARIO)

    assert code == crawl_script.EXIT_RUN_FAILED
    assert "整輪失敗：匯率下載器整個炸了" in log


def test_已有一輪在跑時結束碼是3(cli, client, confirm_card):
    confirm_card(client, LUCARIO)
    client.app.state.crawl_runs.start(TRIGGER_SCHEDULED, DEFAULT_NOW)

    code, log = cli()

    # 這不是失敗，是這次沒得跑。說成失敗會讓排程歷程長出假的紅字。
    assert code == crawl_script.EXIT_ALREADY_RUNNING
    assert "跳過" in log


def test_被鎖擋下時不對SNKRDUNK送出任何請求(cli, snkrdunk, client, confirm_card):
    confirm_card(client, LUCARIO)
    client.app.state.crawl_runs.start(TRIGGER_SCHEDULED, DEFAULT_NOW)

    cli()

    assert snkrdunk.requests == []


def test_匯率沒抓到不算失敗但log說得出原因(cli, fx):
    fx.fails_with = "連不上臺銀"

    code, log = cli(LUCARIO)

    # 成交抓到了，只是換算不了。下一輪會自動重試（ADR-0016），不該讓排程變紅字。
    assert code == crawl_script.EXIT_OK
    assert "匯率沒抓到：連不上臺銀" in log
    assert "一筆都沒丟" in log


# --- 乾跑 ---------------------------------------------------------------


def test_乾跑列出會爬哪些卡種(cli):
    code, log = cli(LUCARIO, PIKACHU_25TH, dry_run=True)

    assert code == crawl_script.EXIT_OK
    assert "MEGA Lucario" in log
    assert "Pikachu 25th" in log


def test_乾跑一個對外請求都不發(cli, snkrdunk, fx):
    cli(LUCARIO, dry_run=True)

    # 設定排程時用它驗證路徑與環境，若會發請求，那個驗證本身就有代價。
    assert snkrdunk.requests == []
    assert fx.requests == []


def test_乾跑不在帳本留下任何一輪(cli, client):
    cli(LUCARIO, dry_run=True)

    assert client.get("/api/market/runs").json() == []


def test_乾跑說得出心跳有沒有設定(cli, heartbeat):
    _, configured = cli(LUCARIO, dry_run=True)
    assert "心跳：已設定" in configured

    heartbeat.url = None
    _, not_configured = cli(dry_run=True)
    assert "未設定" in not_configured


# --- log ---------------------------------------------------------------


def test_輸出寫進當天日期的log檔(cli, tmp_path):
    cli(LUCARIO)

    assert (tmp_path / "logs" / "crawl-2026-08-26.log").exists()


def test_同一天跑第二輪時接在同一個檔案後面(cli):
    cli(LUCARIO)
    _, log = cli()

    # 覆寫會讓當天稍早那一輪的紀錄消失，而那正是事後要查的東西。
    assert log.count("開始一輪爬取") == 2


def test_每一行都帶著時間戳(cli):
    _, log = cli(LUCARIO)

    lines = [line for line in log.splitlines() if line]
    assert lines, "至少要有一行"
    for line in lines:
        assert line.startswith("2026-08-26T"), line
