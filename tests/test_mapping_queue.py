"""待確認清單的外部行為。

斷言一律走 HTTP API，不讀資料庫內部——資料庫換結構時這些測試不必改。
"""

import hashlib
from datetime import timedelta
from pathlib import Path

from conftest import DEFAULT_NOW, LUCARIO

EXPECTED_CARD_COUNT = 68


def _queue(client) -> list[dict]:
    response = client.get("/api/mapping/queue")
    assert response.status_code == 200
    return response.json()


def test_清單列出七十個相異卡種(client):
    # Arrange / Act
    rows = _queue(client)

    # Assert
    assert len(rows) == EXPECTED_CARD_COUNT


def test_清單順序在重複請求間保持穩定(client):
    # Act
    first = _queue(client)
    second = _queue(client)

    # Assert
    assert [row["id"] for row in first] == [row["id"] for row in second]


def test_卡號正規化為三位數並保留原始寫法(client):
    # Act
    rows = _queue(client)
    by_raw = {(row["series_raw"], row["number_raw"]) for row in rows}
    normalized = {
        (row["number_raw"], row["number_normalized"]) for row in rows
    }

    # Assert
    assert ("S8a", "1") in by_raw, "原始卡號應原樣保存"
    assert ("1", "001") in normalized
    assert ("24", "024") in normalized
    assert all(len(row["number_normalized"]) == 3 for row in rows)


def test_系列代碼原樣保留不做收斂(client):
    # Act
    rows = _queue(client)

    # Assert：系列代碼本身決定語言，收斂會讓不同語言的系列被混為一談
    assert all(row["series_normalized"] == row["series_raw"] for row in rows)
    assert any(row["series_raw"] == "SV-P" for row in rows)


def test_錯體版與正常版各自佔一列(client):
    # Act
    rows = _queue(client)
    lucario = sorted(
        row["card_name_raw"]
        for row in rows
        if row["series_raw"] == "M2a" and row["number_raw"] == "228"
    )

    # Assert
    assert lucario == ["MEGA Lucario", "MEGA Lucario Printing Error"]


def test_兩張二十五週年特典卡各自佔一列(client):
    # Act
    rows = _queue(client)
    promos = sorted(
        row["card_name_raw"]
        for row in rows
        if row["series_raw"] == "S8a" and row["number_raw"] == "1"
    )

    # Assert
    assert promos == ["Charizard 25th", "Pikachu 25th"]


def test_每一列初始狀態為待處理(client):
    # Act
    rows = _queue(client)

    # Assert
    assert all(row["status"] == "pending" for row in rows)


def test_進度顯示全數待處理(client):
    # Act
    progress = client.get("/api/mapping/progress").json()

    # Assert
    assert progress == {"confirmed": 0, "rejected": 0, "pending": EXPECTED_CARD_COUNT}


def test_limit_參數只取回一批(client):
    # Act
    response = client.get("/api/mapping/queue", params={"limit": 5})

    # Assert
    assert len(response.json()) == 5


def test_重複啟動不會重複匯入(client_factory):
    # Act：同一個資料庫啟動兩次
    for _ in range(2):
        with client_factory() as client:
            rows = client.get("/api/mapping/queue").json()

    # Assert
    assert len(rows) == EXPECTED_CARD_COUNT


def test_原始CSV未被程式寫入(client, notion_csv: Path):
    # Arrange
    digest_before = hashlib.sha256(notion_csv.read_bytes()).hexdigest()

    # Act
    _queue(client)
    client.get("/api/mapping/progress")

    # Assert
    assert hashlib.sha256(notion_csv.read_bytes()).hexdigest() == digest_before


def test_佇列頁列出全部待確認卡種(client):
    # Act
    response = client.get("/queue")

    # Assert
    assert response.status_code == 200
    assert "MEGA Lucario Printing Error" in response.text
    assert "待處理 68" in response.text


def test_一次只露出一張待處理卡種並顯示進度(client):
    import re

    # Act
    html = client.get("/queue").text

    # Assert：待處理卡種都在 DOM 裡（跳過才不必再打伺服器），但只有第一張露出來，
    # 其餘都 hidden（spec §10.4）
    articles = re.findall(r'<article class="focus" data-row="\d+"( hidden)?>', html)
    assert len(articles) > 1
    assert articles.count("") == 1, "只有一張待處理卡種是露出的"
    # 進度以 N / M 呈現
    assert re.search(r'class="focus__index">\d+</span>\s*/\s*\d+', html)


def test_沒有待處理卡種時給一句話而不是空骨架(client_factory, write_notion_csv):
    # Arrange：一筆持有品都沒有 → 一個待確認卡種都沒有
    empty = write_notion_csv()

    # Act
    with client_factory(csv_path=empty) as client:
        html = client.get("/queue").text

    # Assert：不渲染空的工作區骨架，只給一句話然後接歷史（spec §10.3）
    assert "目前沒有待處理卡種" in html
    assert '<article class="focus"' not in html
    assert '<div class="workspace"' not in html
    # 一句話排在歷史分頁之前
    assert html.index("目前沒有待處理卡種") < html.index('id="hist-confirmed"')


def test_佇列頁提供跳過稍後處理的入口(client):
    # Act
    html = client.get("/queue").text

    # Assert：可以跳過稍後處理（spec §10.4），且跳過是純前端、不打任何端點
    assert "跳過，稍後處理" in html
    assert "skipFocus(this)" in html


def test_歷史有兩個分頁並提供即時篩選(client, confirm_card):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    html = client.get("/queue").text

    # Assert：已確認 / 不納入行情兩個分頁 + 客戶端即時篩選（spec §10.11）
    assert 'for="hist-confirmed"' in html and 'for="hist-excluded"' in html
    assert 'oninput="filterHistory(this.value)"' in html
    assert 'data-search=' in html  # 每一列帶可篩選的卡名／系列／卡號


def test_卡種對應頁不顯示全站行情警示(client_factory, confirm_card, crawl):
    # Arrange：把行情弄成「從未成功」與「已過期」都試過
    with client_factory() as fresh:
        assert "從未成功更新過行情" not in fresh.get("/queue").text

    with client_factory() as client:
        confirm_card(client, LUCARIO)
        crawl(client)
    with client_factory(now=DEFAULT_NOW + timedelta(hours=30)) as stale:
        html = stale.get("/queue").text

    # Assert：卡種對應是對應作業頁、不呈現任何金額，行情新舊不影響判斷（#28 決定二）
    assert "從未成功更新過行情" not in html
    assert "已超過 24 小時沒有成功更新" not in html
    assert 'class="freshness' not in html


def test_窄畫面候選直向堆疊(client):
    # Act：透過 TestClient 取樣式表（#29 的先例）
    css = client.get("/static/queue.css").text

    # Assert：手機上候選直向堆疊、觸控目標可用（spec §11.6）
    assert "@media (max-width: 767px)" in css
    mobile = css.split("@media (max-width: 767px)", 1)[1]
    assert "grid-template-columns: 1fr" in mobile


def test_原始欄位與來源CSV逐字相同(client, notion_csv: Path):
    # Arrange：直接從來源 CSV 取三個原始欄位，不經任何處理
    import csv

    with notion_csv.open(encoding="utf-8-sig", newline="") as handle:
        expected = {
            (holding["set name"], holding["card num"], holding["card name"])
            for holding in csv.DictReader(handle)
        }

    # Act
    rows = _queue(client)

    # Assert
    actual = {
        (row["series_raw"], row["number_raw"], row["card_name_raw"]) for row in rows
    }
    assert actual == expected
