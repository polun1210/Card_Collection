"""市值、待審與對應關係一致性的外部行為。

市值的定義只有一個：近 30 天成交紀錄的中位數（ADR-0002），且一律揭露樣本的
形狀（ADR-0015）。這裡驗證的是「數字對」以及「不夠的地方有說出來」。
"""

from datetime import UTC, datetime

from conftest import BEFORE_FX_RANGE, LUCARIO, OLD_TRADES, PRINTING_ERROR

LATER = datetime(2026, 9, 30, tzinfo=UTC)


def _market(client, apparel_id: int) -> dict | None:
    response = client.get(f"/api/cards/{apparel_id}/market")
    assert response.status_code == 200, response.text
    return response.json()["market_value"]


def _all_values(client) -> list[dict]:
    response = client.get("/api/market/values")
    assert response.status_code == 200, response.text
    return response.json()


def _quarantine(client) -> list[dict]:
    return client.get("/api/market/quarantine").json()


def _holdings(client) -> list[dict]:
    return client.get("/api/holdings").json()


# --- 市值 ---------------------------------------------------------------


def test_市值是近30天成交紀錄的中位數(client, confirm_card, crawl):
    # Arrange：20 筆成交，中位數 6140 日圓，當日即期買入 0.19790
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    value = _market(client, LUCARIO[3])

    # Assert：單一筆離群成交不會讓總市值劇烈跳動
    assert value["market_value_twd"] == 1215


def test_市值揭露樣本筆數與涵蓋期間(client, confirm_card, crawl):
    # Arrange：熱門卡的 20 筆上限只夠涵蓋兩天
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    value = _market(client, LUCARIO[3])

    # Assert：數字沒錯，不足的是樣本，而樣本的形狀就寫在旁邊
    assert value["sample_count"] == 20
    assert value["sample_from"] == "2026-08-24"
    assert value["sample_to"] == "2026-08-25"


def test_近30天有成交時不標註過期天數(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    value = _market(client, LUCARIO[3])

    # Assert：沒過期就沒有這個欄位，0 不會被誤讀成「今天的價」
    assert "stale_days" not in value


def test_近30天無成交時沿用最後一次算得出的市值(client_factory, confirm_card, crawl):
    # Arrange：這張卡最新的成交在 2026-08-06
    with client_factory() as client:
        confirm_card(client, OLD_TRADES)
        crawl(client)

    # Act：把時鐘撥到 55 天後
    with client_factory(now=LATER) as later:
        value = _market(later, OLD_TRADES[3])

    # Assert：畫面不會突然變成空白，而且看得出這個數字有多舊
    assert value["market_value_twd"] == 374255
    assert value["stale_days"] == 55
    assert value["as_of"] == "2026-08-06"


def test_不自動放寬時間窗口去湊資料(client_factory, confirm_card, crawl):
    # Arrange：這張卡總共有 20 筆成交，最舊的在 2026-03-09
    with client_factory() as client:
        confirm_card(client, OLD_TRADES)
        crawl(client)

    # Act
    with client_factory(now=LATER) as later:
        value = _market(later, OLD_TRADES[3])

    # Assert：沿用的仍是「某一天的近 30 天中位數」，不是把全部 20 筆拿來算
    assert value["sample_count"] == 5
    assert value["sample_from"] == "2026-07-09"
    assert value["sample_to"] == "2026-08-06"


def test_從未抓到任何成交的卡種不顯示市值(client, confirm_card):
    # Arrange：確認了對應，但還沒按過更新行情
    confirm_card(client, LUCARIO)

    # Act
    value = _market(client, LUCARIO[3])

    # Assert：不為了填滿版面而編一個數字
    assert value is None


def test_全站只有一個市值定義(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    listed = {value["apparel_id"]: value for value in _all_values(client)}

    # Assert：同一張卡不會在兩個地方顯示不同價格
    assert len(listed) == 2
    for apparel_id, entry in listed.items():
        assert _market(client, apparel_id) == entry["market_value"]


def test_沒有市值的卡種不出現在市值清單裡(client, confirm_card, crawl):
    # Arrange：這張卡的成交全部因為查無匯率而待審
    confirm_card(client, LUCARIO)
    confirm_card(client, BEFORE_FX_RANGE)
    crawl(client)

    # Act
    listed = [value["apparel_id"] for value in _all_values(client)]

    # Assert
    assert listed == [LUCARIO[3]]


# --- 待審 ---------------------------------------------------------------


def test_待審的成交紀錄不參與中位數(client, snkrdunk, confirm_card, crawl):
    # Arrange：篩選失效時混進一筆 2 枚組，它的總價遠高於單張價
    snkrdunk.variant_filter_ignored = True
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    value = _market(client, LUCARIO[3])

    # Assert：可疑資料不會污染中位數
    assert value["sample_count"] == 19
    assert len(_quarantine(client)) == 1


def test_待審清單列出每筆的待審原因(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, BEFORE_FX_RANGE)

    # Act
    crawl(client)
    quarantined = _quarantine(client)

    # Assert：我知道有哪些資料被擋下來、為什麼
    assert len(quarantined) == 7
    assert all(sale["quarantine_reason"] for sale in quarantined)
    assert all(sale["apparel_id"] == BEFORE_FX_RANGE[3] for sale in quarantined)


def test_持有品頁面列出待審成交與原因(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, BEFORE_FX_RANGE)

    # Act
    crawl(client)
    page = client.get("/holdings")

    # Assert：被擋下來的資料沒有被丟掉，也沒有被藏起來
    assert page.status_code == 200
    assert "待審成交（7 筆）" in page.text
    assert "查無成交當日匯率" in page.text


# --- 一致性 -------------------------------------------------------------


def test_推翻卡種確認時一併刪除該卡種的成交紀錄(client, confirm_card, crawl):
    # Arrange
    row_id = confirm_card(client, LUCARIO)
    crawl(client)
    assert _market(client, LUCARIO[3])["market_value_twd"] == 1215

    # Act
    response = client.delete(f"/api/mapping/confirm/{row_id}")

    # Assert：不會留下依據錯誤對應抓來的行情
    assert response.status_code == 200, response.text
    assert client.get(f"/api/cards/{LUCARIO[3]}/market").status_code == 404
    assert _all_values(client) == []


def test_推翻確認後該卡種的持有品仍然存在(client, confirm_card, crawl):
    # Arrange
    row_id = confirm_card(client, LUCARIO)
    crawl(client)

    # Act
    client.delete(f"/api/mapping/confirm/{row_id}")

    # Assert：手上的實體卡不會因為重新對應而消失，只是暫時沒有市值
    lucarios = [
        holding
        for holding in _holdings(client)
        if (holding["series_raw"], holding["number_raw"], holding["card_name_raw"])
        == LUCARIO[:3]
    ]
    assert len(lucarios) == 3
    assert all("unrealized_pnl_twd" not in holding for holding in lucarios)


def test_重新確認後可以再抓一次行情(client, confirm_card, crawl):
    # Arrange
    row_id = confirm_card(client, LUCARIO)
    crawl(client)
    client.delete(f"/api/mapping/confirm/{row_id}")

    # Act
    confirm_card(client, LUCARIO)
    result = crawl(client)

    # Assert：刪乾淨了，所以整批重新入庫
    assert result["cards"][0]["inserted"] == 20
    assert _market(client, LUCARIO[3])["market_value_twd"] == 1215
