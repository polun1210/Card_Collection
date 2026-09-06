"""持有品匯入與已實現損益的外部行為。

斷言一律走 HTTP，不讀資料庫內部。金額一律為新台幣整數。
"""

import pytest

TOTAL_HOLDINGS = 100
HELD_COUNT = 89
SOLD_COUNT = 11
HELD_COST_TWD = 1_016_730
REALIZED_PNL_TWD = 86_108

MEGA_LUCARIO = 722241

VALID_HOLDING = {
    "card name": "MEGA Lucario",
    "card num": "228",
    "cost": "2600",
    "grading score": "PSA 10",
    "purchase date": "2026/3/15",
    "set name": "M2a",
}


def _holdings(client) -> list[dict]:
    response = client.get("/api/holdings")
    assert response.status_code == 200, response.text
    return response.json()


def _summary(client) -> dict:
    response = client.get("/api/holdings/summary")
    assert response.status_code == 200, response.text
    return response.json()


def _of_kind(client, series: str, number: str, card_name: str) -> list[dict]:
    return [
        holding
        for holding in _holdings(client)
        if (holding["series_raw"], holding["number_raw"], holding["card_name_raw"])
        == (series, number, card_name)
    ]


def _confirm_mega_lucario(client) -> None:
    row = next(
        row
        for row in client.get("/api/mapping/queue").json()
        if (row["series_raw"], row["number_raw"], row["card_name_raw"])
        == ("M2a", "228", "MEGA Lucario")
    )
    response = client.post(
        "/api/mapping/confirm",
        json={"mapping_candidate_id": row["id"], "apparel_id": MEGA_LUCARIO},
    )
    assert response.status_code == 200, response.text


# --- 匯入 ---------------------------------------------------------------


def test_匯入CSV裡的每一筆持有品(client):
    # Act
    holdings = _holdings(client)

    # Assert
    assert len(holdings) == TOTAL_HOLDINGS


def test_欄位完全相同的列各自佔一筆持有品(client):
    # Act：三張同款同價的實體卡，靠內容去重會吃掉其中兩張
    charizards = _of_kind(client, "S8b", "187", "Charizard")

    # Assert
    assert len(charizards) == 7
    assert [holding["cost_twd"] for holding in charizards].count(2885) == 3
    assert len({holding["id"] for holding in charizards}) == 7


def test_同一個卡種的多筆持有品各自保有成本(client):
    # Act
    lucarios = _of_kind(client, "M2a", "228", "MEGA Lucario")

    # Assert：不做平均成本，每一張的成本都在
    assert sorted(holding["cost_twd"] for holding in lucarios) == [2400, 2600, 2650]


def test_持有品帶著來源列號對得回CSV(client):
    # Act
    lucarios = _of_kind(client, "M2a", "228", "MEGA Lucario")

    # Assert：CSV 資料列由 1 起算，不含標頭
    assert sorted(holding["source_row_number"] for holding in lucarios) == [10, 12, 68]


def test_鑑定分數原樣保存(client):
    # Act
    holdings = _holdings(client)

    # Assert：全系統只認 PSA 10，此欄不參與判斷但不丟棄
    assert all(holding["grading_raw"] == "PSA 10" for holding in holdings)


def test_購入日正規化為可排序格式並保留原始寫法(client):
    # Act
    lucario = _of_kind(client, "M2a", "228", "MEGA Lucario")[0]

    # Assert
    assert lucario["purchase_date"] == "2026-03-15"
    assert lucario["purchase_date_raw"] == "2026/3/15"


def test_持有品清單順序在重複請求間保持穩定(client):
    # Act
    first = _holdings(client)
    second = _holdings(client)

    # Assert
    assert [holding["id"] for holding in first] == [holding["id"] for holding in second]


def test_匯入帳本記錄來源與筆數(client):
    # Act
    response = client.get("/api/holdings/imports")

    # Assert
    assert response.status_code == 200
    ledger = response.json()
    assert len(ledger) == 1
    assert ledger[0]["row_count"] == TOTAL_HOLDINGS
    assert ledger[0]["source_path"].endswith(".csv")
    assert ledger[0]["imported_at"]


# --- 持有中與已售出 -----------------------------------------------------


def test_持有中與已售出依售出日判定(client):
    # Act
    holdings = _holdings(client)

    # Assert
    held = [holding for holding in holdings if holding["status"] == "held"]
    sold = [holding for holding in holdings if holding["status"] == "sold"]
    assert (len(held), len(sold)) == (HELD_COUNT, SOLD_COUNT)
    assert all(holding["sold_date"] is None for holding in held)
    assert all(holding["sold_date"] for holding in sold)


def test_未售出的售出日與售出價為空值而非零(client):
    # Act
    held = [holding for holding in _holdings(client) if holding["status"] == "held"]

    # Assert：0 會被誤讀為「以 0 元賣出」，已實現損益將算成 −100%
    assert all(holding["sold_price_twd"] is None for holding in held)
    assert all(holding["sold_date_raw"] is None for holding in held)


def test_同一個卡種可以同時有持有中與已售出(client):
    # Act
    charizards = _of_kind(client, "S8a", "1", "Charizard 25th")

    # Assert
    assert sorted(holding["status"] for holding in charizards) == ["held", "sold"]


# --- 已實現損益 ---------------------------------------------------------


def test_已售出的持有品帶著已實現損益(client):
    # Act
    sold = next(
        holding
        for holding in _of_kind(client, "S8a", "1", "Charizard 25th")
        if holding["status"] == "sold"
    )

    # Assert
    assert (sold["cost_twd"], sold["sold_price_twd"]) == (19800, 32888)
    assert sold["realized_pnl_twd"] == 13088


def test_報酬率採報酬率定義而非倍數(client):
    # Act
    sold = next(
        holding
        for holding in _of_kind(client, "S8a", "1", "Charizard 25th")
        if holding["status"] == "sold"
    )

    # Assert：(結果 − 成本) ÷ 成本，不是 結果 ÷ 成本
    assert sold["return_rate"] == pytest.approx(13088 / 19800)


def test_持有中的持有品不出現損益欄位(client):
    # Act
    held = [holding for holding in _holdings(client) if holding["status"] == "held"]

    # Assert：市值還不存在，欄位就不該出現——不是 null，也不是 0
    assert all("realized_pnl_twd" not in holding for holding in held)
    assert all("return_rate" not in holding for holding in held)
    assert all("unrealized_pnl_twd" not in holding for holding in held)


# --- 統計 ---------------------------------------------------------------


def test_全站統計含持有成本與已實現損益合計(client):
    # Act
    summary = _summary(client)

    # Assert
    assert summary == {
        "held_count": HELD_COUNT,
        "sold_count": SOLD_COUNT,
        "held_cost_twd": HELD_COST_TWD,
        "realized_pnl_twd": REALIZED_PNL_TWD,
        # 還沒爬過行情，89 張全部沒有市值。市值相關的合計一律附上涵蓋張數，
        # 否則 0 會被讀成「不賺不賠」而不是「還沒有資料」。
        "valued_count": 0,
        "unvalued_count": HELD_COUNT,
        "held_cost_valued_twd": 0,
        "held_market_value_twd": 0,
        "unrealized_pnl_twd": 0,
    }


def test_已售出的持有品不計入持有成本(client):
    # Act
    summary = _summary(client)
    held_cost = sum(
        holding["cost_twd"]
        for holding in _holdings(client)
        if holding["status"] == "held"
    )

    # Assert
    assert summary["held_cost_twd"] == held_cost


def test_單一卡種的持有品與統計(client):
    # Arrange
    _confirm_mega_lucario(client)

    # Act
    response = client.get(f"/api/cards/{MEGA_LUCARIO}/holdings")

    # Assert
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["holdings"]) == 3
    assert payload["summary"] == {
        "held_count": 3,
        "sold_count": 0,
        "held_cost_twd": 2400 + 2600 + 2650,
        "realized_pnl_twd": 0,
        "valued_count": 0,
        "unvalued_count": 3,
        "held_cost_valued_twd": 0,
        "held_market_value_twd": 0,
        "unrealized_pnl_twd": 0,
    }


def test_查詢不在主檔的卡種持有品回404(client):
    # Act
    response = client.get("/api/cards/999999/holdings")

    # Assert
    assert response.status_code == 404


def test_全部賣光的卡種持有成本為零但已實現損益仍在(client):
    # Act
    rayquazas = _of_kind(client, "S8b", "252", "Rayquaza")

    # Assert：賣光是正常狀態，不是錯誤
    assert len(rayquazas) == 2
    assert all(holding["status"] == "sold" for holding in rayquazas)
    assert all(holding["realized_pnl_twd"] for holding in rayquazas)


# --- 重啟 ---------------------------------------------------------------


def test_重啟服務後不重複匯入(client_factory):
    # Arrange
    with client_factory() as first:
        assert len(_holdings(first)) == TOTAL_HOLDINGS

    # Act
    with client_factory() as second:
        holdings = _holdings(second)
        ledger = second.get("/api/holdings/imports").json()

    # Assert
    assert len(holdings) == TOTAL_HOLDINGS
    assert len(ledger) == 1


def test_重啟服務後統計不變(client_factory):
    # Arrange
    with client_factory() as first:
        before = _summary(first)

    # Act
    with client_factory() as second:
        after = _summary(second)

    # Assert
    assert after == before


# --- 不合格來源資料：整批失敗 -------------------------------------------


def _import_fails(client_factory, csv_path) -> str:
    with pytest.raises(Exception) as failure:  # noqa: B017 - 啟動即失敗，型別由訊息驗證
        with client_factory(csv_path):
            pass
    return str(failure.value)


def test_有售出日但無售出價時整批匯入失敗(client_factory, write_notion_csv):
    # Arrange
    csv_path = write_notion_csv(VALID_HOLDING | {"sold date": "2026/5/6"})

    # Act / Assert
    assert "售出價" in _import_fails(client_factory, csv_path)


def test_有售出價但無售出日時整批匯入失敗(client_factory, write_notion_csv):
    # Arrange
    csv_path = write_notion_csv(VALID_HOLDING | {"sold price": "32888"})

    # Act / Assert
    assert "售出日" in _import_fails(client_factory, csv_path)


def test_售出日早於購入日時整批匯入失敗(client_factory, write_notion_csv):
    # Arrange
    csv_path = write_notion_csv(
        VALID_HOLDING | {"sold date": "2026/1/1", "sold price": "32888"}
    )

    # Act / Assert
    assert "早於" in _import_fails(client_factory, csv_path)


def test_購入成本為空時整批匯入失敗(client_factory, write_notion_csv):
    # Arrange
    csv_path = write_notion_csv(VALID_HOLDING | {"cost": ""})

    # Act / Assert
    assert "購入成本" in _import_fails(client_factory, csv_path)


def test_購入成本非正整數時整批匯入失敗(client_factory, write_notion_csv):
    # Arrange
    csv_path = write_notion_csv(VALID_HOLDING | {"cost": "0"})

    # Act / Assert
    assert "購入成本" in _import_fails(client_factory, csv_path)


def test_購入日為空時整批匯入失敗(client_factory, write_notion_csv):
    # Arrange
    csv_path = write_notion_csv(VALID_HOLDING | {"purchase date": ""})

    # Act / Assert
    assert "購入日" in _import_fails(client_factory, csv_path)


def test_日期寫法無法解析時整批匯入失敗(client_factory, write_notion_csv):
    # Arrange
    csv_path = write_notion_csv(VALID_HOLDING | {"purchase date": "去年三月"})

    # Act / Assert
    assert "去年三月" in _import_fails(client_factory, csv_path)


def test_匯入失敗的訊息指出來源列號(client_factory, write_notion_csv):
    # Arrange：第一列合格，第二列的售出價缺漏
    csv_path = write_notion_csv(VALID_HOLDING, VALID_HOLDING | {"sold date": "2026/5/6"})

    # Act / Assert
    assert "第 2 列" in _import_fails(client_factory, csv_path)


def test_匯入失敗後資料庫不留半成品(client_factory, write_notion_csv):
    # Arrange
    broken = write_notion_csv(VALID_HOLDING, VALID_HOLDING | {"cost": ""})
    _import_fails(client_factory, broken)

    # Act：同一個暫存資料庫，換回合格的 CSV
    with client_factory() as client:
        holdings = _holdings(client)
        ledger = client.get("/api/holdings/imports").json()

    # Assert：失敗那次若寫進了半筆，這裡就會多出來
    assert len(holdings) == TOTAL_HOLDINGS
    assert len(ledger) == 1


# --- 頁面 ---------------------------------------------------------------


def test_持有品頁面列出卡種張數與成本(client):
    # 意圖不變（頁面按卡種列出張數與成本），寫法改為驗**每個卡種自己的**數字。
    # 舊版驗的是頁頂全頁彙總 HELD_COST_TWD / REALIZED_PNL_TWD——那組與首頁儀表板
    # 重複的數字已依 #34 移除（uiux-spec §9.1），彙總不重複這條由
    # test_unrealized.py::test_持有品頁面不重複首頁的彙總數字 反向守住。

    # Act
    response = client.get("/holdings")

    # Assert
    assert response.status_code == 200
    html = response.text
    # MEGA Lucario（M2a #228）這一組：3 張持有中、合計成本 2400+2600+2650=7,650。
    assert "MEGA Lucario" in html
    assert "M2a #228" in html
    assert f"{2400 + 2600 + 2650:,}" in html


def test_持有品頁面顯示已確認卡種的卡圖(client):
    # Arrange
    _confirm_mega_lucario(client)

    # Act
    html = client.get("/holdings").text

    # Assert
    assert f"/api/cards/{MEGA_LUCARIO}/image" in html
