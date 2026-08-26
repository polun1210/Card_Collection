"""待確認清單的外部行為。

斷言一律走 HTTP API，不讀資料庫內部——資料庫換結構時這些測試不必改。
"""

import hashlib
from pathlib import Path

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
