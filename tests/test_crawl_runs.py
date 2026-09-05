"""爬取帳本、鎖、過期警示與心跳的外部行為。

這一組測試守的是同一件事：**自動化之後，失敗不准變成安靜的**。
"""

from datetime import timedelta

import pytest

from card_collection.crawl_runs import (
    STALE_LOCK_MINUTES,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
)
from conftest import DEFAULT_NOW, LUCARIO, PIKACHU_25TH


def _latest(client) -> dict:
    return client.get("/api/market/runs/latest").json()


def _runs(client) -> list[dict]:
    return client.get("/api/market/runs").json()


# --- 帳本 ---------------------------------------------------------------


def test_每一輪爬取都在帳本留下一筆紀錄(client, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    report = crawl(client)

    runs = _runs(client)
    assert len(runs) == 1
    assert runs[0]["id"] == report["run_id"]
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["finished_at"] is not None


def test_帳本分得出手動觸發與排程觸發(client, confirm_card):
    confirm_card(client, LUCARIO)
    client.post("/api/market/crawl")
    client.app.state.market_service.crawl(trigger=TRIGGER_SCHEDULED)

    triggers = [run["trigger"] for run in _runs(client)]
    assert triggers == [TRIGGER_SCHEDULED, TRIGGER_MANUAL]


def test_帳本記下這一輪的統計(client, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    report = crawl(client)

    run = _runs(client)[0]
    assert run["card_count"] == report["totals"]["cards"]
    assert run["fetched"] == report["totals"]["fetched"]
    assert run["inserted"] == report["totals"]["inserted"]
    assert run["quarantined"] == report["totals"]["quarantined"]
    assert run["skipped_count"] == report["totals"]["skipped"]
    assert run["fx_converted"] == report["fx"]["converted"]


def test_整輪失敗時帳本留下失敗與原因(client, fx, confirm_card):
    confirm_card(client, LUCARIO)
    fx.crashes_with = "匯率下載器整個炸了"

    with pytest.raises(RuntimeError):
        client.post("/api/market/crawl")

    run = _runs(client)[0]
    # 停在 running 就等於冒充「還在跑」，同時把鎖一直握著。
    assert run["status"] == "failed"
    assert "匯率下載器整個炸了" in run["error"]
    assert run["finished_at"] is not None


def test_單張卡失敗的清單記進帳本(client, snkrdunk, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    confirm_card(client, PIKACHU_25TH)
    snkrdunk.trading_fails_for = {LUCARIO[4]}

    crawl(client)

    failures = _runs(client)[0]["failures"]
    assert [failure["card_name_raw"] for failure in failures] == ["MEGA Lucario"]
    assert failures[0]["reason"]


def test_匯率來源錯誤獨立記在帳本上(client, fx, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    fx.fails_with = "連不上臺銀"

    crawl(client)

    run = _runs(client)[0]
    # 成交抓到了，只是換算不了。這一輪不算失敗，但原因必須落地。
    assert run["status"] == "succeeded"
    assert "連不上臺銀" in run["fx_error"]


def test_沒有跑過任何一輪時帳本是空的(client):
    assert _runs(client) == []


# --- 同時只允許一輪 -------------------------------------------------------


def test_已有一輪在跑時第二次觸發回409(client, confirm_card):
    confirm_card(client, LUCARIO)
    run_id = client.app.state.crawl_runs.start(TRIGGER_SCHEDULED, DEFAULT_NOW)

    response = client.post("/api/market/crawl")

    assert response.status_code == 409
    assert response.json()["detail"]["run_id"] == run_id


def test_被409擋下時不對SNKRDUNK送出任何請求(client, snkrdunk, confirm_card):
    confirm_card(client, LUCARIO)
    client.app.state.crawl_runs.start(TRIGGER_SCHEDULED, DEFAULT_NOW)
    snkrdunk.requests.clear()

    client.post("/api/market/crawl")

    # 重複觸發若還是送請求出去，禮貌間隔的紀律就等於沒有。
    assert snkrdunk.requests == []


def test_被409擋下時不送出心跳(client, heartbeat, confirm_card):
    confirm_card(client, LUCARIO)
    client.app.state.crawl_runs.start(TRIGGER_SCHEDULED, DEFAULT_NOW)

    client.post("/api/market/crawl")

    assert heartbeat.sent == []


def test_卡死的鎖超過門檻會自己解開(client, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    abandoned = DEFAULT_NOW - timedelta(minutes=STALE_LOCK_MINUTES + 1)
    client.app.state.crawl_runs.start(TRIGGER_SCHEDULED, abandoned)

    # 少了自解，一次當機就會讓爬取永遠啟動不了。
    report = crawl(client)

    assert report["run_id"]
    assert _runs(client)[0]["status"] == "succeeded"


def test_被自動解開的那一輪說得出它是判定行程已死(client, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    abandoned = DEFAULT_NOW - timedelta(minutes=STALE_LOCK_MINUTES + 1)
    client.app.state.crawl_runs.start(TRIGGER_SCHEDULED, abandoned)

    crawl(client)

    dead = _runs(client)[1]
    assert dead["status"] == "failed"
    # 它不是一次真正的爬取失敗，畫面與日後稽核都必須分得出來。
    assert "行程已死" in dead["error"]


def test_還沒超過門檻的那一輪不會被搶走(client, confirm_card):
    confirm_card(client, LUCARIO)
    recent = DEFAULT_NOW - timedelta(minutes=STALE_LOCK_MINUTES - 1)
    client.app.state.crawl_runs.start(TRIGGER_SCHEDULED, recent)

    assert client.post("/api/market/crawl").status_code == 409


# --- 過期警示 -----------------------------------------------------------


def test_從未成功爬取過時判定為過期(client):
    latest = _latest(client)

    # 第一次就壞掉的情況若不算過期，它會被當成正常。
    assert latest["never_succeeded"] is True
    assert latest["is_stale"] is True


def test_剛爬完不算過期(client, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    crawl(client)

    latest = _latest(client)
    assert latest["never_succeeded"] is False
    assert latest["is_stale"] is False
    assert latest["age_label"] == "不到 1 小時"


def test_超過24小時未成功就算過期(client_factory, confirm_card, crawl):
    with client_factory() as client:
        confirm_card(client, LUCARIO)
        crawl(client)

    with client_factory(now=DEFAULT_NOW + timedelta(hours=25)) as later:
        latest = _latest(later)
        assert latest["is_stale"] is True
        assert latest["age_label"] == "25 小時"


def test_失敗的那一輪不算更新過(client, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    crawl(client)
    runs = client.app.state.crawl_runs
    runs.fail(runs.start(TRIGGER_SCHEDULED, DEFAULT_NOW), "來源改版", DEFAULT_NOW)

    latest = _latest(client)
    # 最近一輪是失敗的，但「上次成功」仍指向前一輪——兩者不能混為一談。失敗既不
    # 算更新過，也不會讓一份剛抓回來的資料立刻變成過期。
    assert latest["latest"]["status"] == "failed"
    assert latest["last_success"]["status"] == "succeeded"
    assert latest["is_stale"] is False


def test_從未成功時畫面顯示警示(client):
    page = client.get("/holdings").text

    assert "從未成功更新過行情" in page


def test_剛爬完畫面不出現行情警示(client, confirm_card, crawl):
    # 健康時不顯示新鮮度橫幅（uiux-spec §7.2）。過期／失敗仍會大聲警示，見
    # test_超過24小時畫面顯示過期警示 與 test_上一輪的卡種失敗直接顯示在畫面上。
    confirm_card(client, LUCARIO)
    crawl(client)

    page = client.get("/holdings").text
    assert "從未成功更新過行情" not in page
    assert "已超過 24 小時沒有成功更新" not in page
    assert 'class="freshness' not in page


def test_超過24小時畫面顯示過期警示(client_factory, confirm_card, crawl):
    with client_factory() as client:
        confirm_card(client, LUCARIO)
        crawl(client)

    with client_factory(now=DEFAULT_NOW + timedelta(hours=25)) as later:
        page = later.get("/holdings").text
        assert "已超過 24 小時沒有成功更新" in page


def test_上一輪的卡種失敗直接顯示在畫面上(client, snkrdunk, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    snkrdunk.trading_fails_for = {LUCARIO[4]}
    crawl(client)

    page = client.get("/holdings").text
    # 壞消息不摺疊起來——要展開才看得到的警示等於沒有警示。
    assert "個卡種抓失敗" in page
    assert "MEGA Lucario" in page


def test_上一輪的匯率錯誤直接顯示在畫面上(client, fx, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    fx.fails_with = "連不上臺銀"
    crawl(client)

    page = client.get("/holdings").text
    assert "上一輪的匯率沒抓到" in page
    assert "連不上臺銀" in page


# --- 心跳 ---------------------------------------------------------------


def test_爬取成功時送出開始與成功兩次心跳(client, heartbeat, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    crawl(client)

    urls = [url for url, _ in heartbeat.sent]
    assert urls == [heartbeat.URL + "/start", heartbeat.URL]


def test_成功的心跳帶著這一輪的健康摘要(client, heartbeat, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    report = crawl(client)

    body = heartbeat.bodies[-1]
    assert f"新增 {report['totals']['inserted']} 筆" in body


def test_整輪失敗時送出失敗心跳(client, heartbeat, fx, confirm_card):
    confirm_card(client, LUCARIO)
    fx.crashes_with = "匯率下載器整個炸了"

    with pytest.raises(RuntimeError):
        client.post("/api/market/crawl")

    url, body = heartbeat.sent[-1]
    assert url == heartbeat.URL + "/fail"
    assert "匯率下載器整個炸了" in body


def test_卡種失敗的原因跟著心跳一起送出去(client, heartbeat, snkrdunk, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    snkrdunk.trading_fails_for = {LUCARIO[4]}
    crawl(client)

    assert "MEGA Lucario" in heartbeat.bodies[-1]


def test_心跳自己失敗時爬取仍然成功(client, heartbeat, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    heartbeat.fails = True

    # 通知管道掛掉不該反過來弄壞資料。
    report = crawl(client)

    assert _runs(client)[0]["status"] == "succeeded"
    assert report["totals"]["inserted"] > 0


def test_心跳送不出去時寫進log而不是無聲失敗(client, heartbeat, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    heartbeat.fails = True

    crawl(client)

    assert any("心跳送不出去" in line for line in heartbeat.logs)


def test_未設定心跳網址時完全不送(client_factory, heartbeat, confirm_card, crawl):
    heartbeat.url = None

    with client_factory() as client:
        confirm_card(client, LUCARIO)
        crawl(client)

    assert heartbeat.sent == []


def test_心跳內容不含任何金額(client, heartbeat, confirm_card, crawl):
    confirm_card(client, LUCARIO)
    crawl(client)

    sales = client.get(f"/api/cards/{LUCARIO[3]}/sales").json()
    assert sales, "這個測試要有成交才有意義"
    amounts = {str(sale["price_jpy"]) for sale in sales}
    amounts |= {str(sale["price_twd"]) for sale in sales if sale["price_twd"]}

    # 市值、成本、售出價、損益一律不出門。訊息由具名欄位組出來，就是為了這件事。
    for body in heartbeat.bodies:
        assert not (amounts & set(body.split())), body
