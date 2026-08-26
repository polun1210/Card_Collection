"""成交紀錄爬取與匯率換算的外部行為。

斷言一律走 HTTP，不讀資料庫內部。外部回應在傳輸層回放錄下來的真實資料。
"""

import json
from collections import Counter

from conftest import FIXTURES, BEFORE_FX_RANGE, LUCARIO, PRINTING_ERROR

LUCARIO_APPAREL, LUCARIO_PRODUCT = LUCARIO[3], LUCARIO[4]
PRINTING_ERROR_APPAREL, PRINTING_ERROR_PRODUCT = PRINTING_ERROR[3], PRINTING_ERROR[4]

TOTAL_CARD_KINDS = 68
SPOT_BUY_20260825 = 0.19790


def _sales(client, apparel_id: int) -> list[dict]:
    response = client.get(f"/api/cards/{apparel_id}/sales")
    assert response.status_code == 200, response.text
    return response.json()


def _quarantine(client) -> list[dict]:
    response = client.get("/api/market/quarantine")
    assert response.status_code == 200, response.text
    return response.json()


def _market(client, apparel_id: int) -> dict | None:
    response = client.get(f"/api/cards/{apparel_id}/market")
    assert response.status_code == 200, response.text
    return response.json()["market_value"]


def _recorded_trades(name: str) -> list[dict]:
    """直接讀那份錄下來的回應，用來逐字比對入庫的原幣金額。"""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["trades"]


def _trading_requests(snkrdunk, product_catalog_id: int) -> list[str]:
    return [
        url
        for url in snkrdunk.requests
        if f"/v3/products/{product_catalog_id}/trading-history" in url
    ]


# --- 爬取 ---------------------------------------------------------------


def test_爬取把已確認卡種的成交紀錄抓回來(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    result = crawl(client)

    # Assert
    assert result["totals"]["cards"] == 1
    assert result["cards"][0]["apparel_id"] == LUCARIO_APPAREL
    assert len(_sales(client, LUCARIO_APPAREL)) == 20


def test_爬取結果逐卡回報抓到幾筆新增幾筆待審幾筆(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    card = crawl(client)["cards"][0]

    # Assert：這一輪到底做了什麼，三個數字都在
    assert card["fetched"] == 20
    assert card["inserted"] == 20
    assert card["quarantined"] == 0


def test_單一卡種抓失敗不影響其他卡種(client, snkrdunk, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)
    confirm_card(client, PRINTING_ERROR)
    snkrdunk.trading_fails_for = {LUCARIO_PRODUCT}

    # Act
    result = crawl(client)

    # Assert：壞掉的那張明確列在 failed，好的那張照樣入庫
    assert [card["apparel_id"] for card in result["cards"]] == [PRINTING_ERROR_APPAREL]
    assert result["totals"]["inserted"] == 20
    assert len(_sales(client, LUCARIO_APPAREL)) == 0


def test_失敗的卡種附上原因而不是被靜默吞掉(client, snkrdunk, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)
    snkrdunk.trading_fails_for = {LUCARIO_PRODUCT}

    # Act
    failed = crawl(client)["failed"]

    # Assert
    assert len(failed) == 1
    assert failed[0]["apparel_id"] == LUCARIO_APPAREL
    assert failed[0]["card_name_raw"] == LUCARIO[2]
    assert "500" in failed[0]["reason"]


def test_重複爬取不會重複寫入同一筆成交(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)
    first = crawl(client)

    # Act：按第二次按鈕
    second = crawl(client)

    # Assert：抓到的一樣多，但一筆都沒新增
    assert first["cards"][0]["inserted"] == 20
    assert second["cards"][0]["fetched"] == 20
    assert second["cards"][0]["inserted"] == 0
    assert len(_sales(client, LUCARIO_APPAREL)) == 20


def test_同一秒同價格的多筆真實成交各自入庫(client, confirm_card, crawl):
    # Arrange：實測 834208 有一組同秒同價同枚数、共三筆的成交
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    identical = Counter(
        (sale["sold_at_raw"], sale["price_jpy"], sale["variant_raw"])
        for sale in _sales(client, LUCARIO_APPAREL)
    )

    # Assert：靠內容去重會把它們吃成一筆，熱門度就少算了
    assert max(identical.values()) == 3


def test_尚未確認的卡種明確列為跳過(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    result = crawl(client)

    # Assert：確認了一個，其餘每一個都要看得見，不是默默不跑
    assert result["totals"]["skipped"] == TOTAL_CARD_KINDS - 1
    assert all(row["reason"] for row in result["skipped"])


def test_成交金額以日圓原幣原樣保存(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    sales = _sales(client, LUCARIO_APPAREL)

    # Assert：與來源回應逐字相同，日後發現換算有誤還回得去
    recorded = _recorded_trades("trading_834208_variant_9595830")
    assert sorted(sale["price_jpy"] for sale in sales) == sorted(
        trade["price"] for trade in recorded
    )


def test_成交紀錄保留SNKRDUNK原始的狀態與枚数文字(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    sales = _sales(client, LUCARIO_APPAREL)

    # Assert：事後才核對得出篩選是否正確
    assert {sale["condition_raw"] for sale in sales} == {"PSA10"}
    assert {sale["variant_raw"] for sale in sales} == {"1枚"}


def test_成交日期一律以日本時間為準(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    sales = _sales(client, LUCARIO_APPAREL)

    # Assert：原始 soldAt 是 UTC，JST 早九小時，同一筆成交在兩處會差一天
    assert all(sale["sold_at_raw"].endswith("Z") for sale in sales)
    assert {sale["sold_date_jst"] for sale in sales} == {"2026-08-24", "2026-08-25"}


def test_多張一組的成交進待審且不參與市值(client, snkrdunk, confirm_card, crawl):
    # Arrange：模擬來源端的枚数篩選失效，20 筆裡混進一筆 2 枚組
    snkrdunk.variant_filter_ignored = True
    confirm_card(client, LUCARIO)

    # Act
    result = crawl(client)

    # Assert：一組兩張的總價不會被誤當成單張價
    assert result["cards"][0]["quarantined"] == 1
    assert _market(client, LUCARIO_APPAREL)["sample_count"] == 19
    assert {sale["quarantine_reason"] for sale in _quarantine(client)} == {
        "多張一組，不是單張"
    }


def test_未篩選就全為單張時不再打第二次請求(client, snkrdunk, confirm_card, crawl):
    # Arrange：實測約三分之一的卡第一次回應就已全為 1 枚
    confirm_card(client, PRINTING_ERROR)

    # Act
    crawl(client)

    # Assert
    assert len(_trading_requests(snkrdunk, PRINTING_ERROR_PRODUCT)) == 1


def test_混有多張組時才打第二次請求並改用篩選後的結果(
    client, snkrdunk, confirm_card, crawl
):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)

    # Assert：未篩選只有 19 筆單張，篩選後拿回 20 筆
    assert len(_trading_requests(snkrdunk, LUCARIO_PRODUCT)) == 2
    assert len(_sales(client, LUCARIO_APPAREL)) == 20


def test_對SNKRDUNK的請求維持序列化且固定間隔(client, snkrdunk, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)
    snkrdunk.sleeps.clear()

    # Act
    crawl(client)

    # Assert：每次請求之間都有等，且間隔固定，不會因為爬太快被擋
    assert len(snkrdunk.sleeps) == 2
    assert set(snkrdunk.sleeps) == {1.0}


# --- 匯率 ---------------------------------------------------------------


def test_每筆成交以成交當日的匯率換算成台幣(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    sale = next(
        sale
        for sale in _sales(client, LUCARIO_APPAREL)
        if sale["sold_date_jst"] == "2026-08-25"
    )

    # Assert：2026-08-25 的即期買入價，不是今天的匯率
    assert sale["fx_rate"] == SPOT_BUY_20260825
    assert sale["price_twd"] == round(sale["price_jpy"] * SPOT_BUY_20260825)


def test_每筆成交記下實際採用的匯率日期與來源(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)
    sales = _sales(client, LUCARIO_APPAREL)

    # Assert：換算過程可稽核，日後換來源時分辨得出哪些數字來自哪裡
    assert {sale["fx_rate_date"] for sale in sales} == {"2026-08-24", "2026-08-25"}
    assert {sale["fx_source"] for sale in sales} == {"bot-spot-buy"}


def test_匯率一經寫入就固定(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)
    crawl(client)
    before = _sales(client, LUCARIO_APPAREL)

    # Act：再跑一輪
    crawl(client)

    # Assert：昨天看到的數字今天不會變
    after = _sales(client, LUCARIO_APPAREL)
    assert [sale["price_twd"] for sale in after] == [
        sale["price_twd"] for sale in before
    ]
    assert [sale["fx_rate"] for sale in after] == [sale["fx_rate"] for sale in before]


def test_只在需要新日期時才去抓匯率(client, fx, confirm_card, crawl):
    # Arrange：第一張卡把匯率抓回來
    confirm_card(client, LUCARIO)
    crawl(client)
    assert len(fx.requests) == 1

    # Act：再確認一張卡，它的成交日期都落在抓過的範圍內
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Assert：已經抓過的日期不重抓
    assert len(fx.requests) == 1


def test_當日牌告尚未掛出時之後還會再去拿(client, fx, confirm_card, crawl):
    # Arrange：臺銀只掛到 08-24，但有成交發生在 08-25
    fx.published_through = "20260824"
    confirm_card(client, LUCARIO)
    crawl(client)
    assert len(fx.requests) == 1
    written = _sales(client, LUCARIO_APPAREL)
    assert {sale["fx_rate_date"] for sale in written} == {"2026-08-24"}

    # Act：牌告掛出來之後，當天稍晚又有新的成交要換算
    fx.published_through = None
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Assert：帳本只記到實際拿到的最新牌告日，所以會再問一次，
    #         新成交用上真正的當日牌告；已寫入的維持原匯率，不回頭重算
    assert len(fx.requests) == 2
    assert _sales(client, LUCARIO_APPAREL) == written
    assert "2026-08-25" in {
        sale["fx_rate_date"] for sale in _sales(client, PRINTING_ERROR_APPAREL)
    }


def test_週末成交沿用前一營業日的匯率(client, confirm_card, crawl):
    # Arrange：2026-08-02 是週日，臺銀當天沒有牌告
    confirm_card(client, PRINTING_ERROR)

    # Act
    crawl(client)
    sunday = next(
        sale
        for sale in _sales(client, PRINTING_ERROR_APPAREL)
        if sale["sold_date_jst"] == "2026-08-02"
    )

    # Assert：週末成交的卡不會因為沒有牌告而卡住，且採用的日期看得見
    assert sunday["fx_rate_date"] == "2026-07-31"
    assert sunday["price_twd"] is not None


def test_匯率抓不到時該筆成交進待審而不用假匯率硬換(client, confirm_card, crawl):
    # Arrange：這張卡的成交全在 2023～2025，早於臺銀六個月的涵蓋範圍
    confirm_card(client, BEFORE_FX_RANGE)

    # Act
    result = crawl(client)

    # Assert：計算裡不會混進編出來的數字
    assert result["cards"][0]["quarantined"] == 7
    assert _market(client, BEFORE_FX_RANGE[3]) is None
    assert {sale["quarantine_reason"] for sale in _quarantine(client)} == {
        "查無成交當日匯率"
    }
    assert all(sale["price_twd"] is None for sale in _quarantine(client))


def test_臺銀回機器人驗證頁時不當成查無匯率(client, fx, confirm_card, crawl):
    # Arrange：驗證頁同樣是 200 且 content-type 為 text/csv，只有內容看得出來
    fx.bot_challenge = True
    confirm_card(client, LUCARIO)

    # Act
    result = crawl(client)

    # Assert：整批進待審，絕不安靜地建立在空資料上
    assert result["cards"][0]["quarantined"] == 20
    assert _market(client, LUCARIO_APPAREL) is None


def test_臺銀回錯格式時不當成查無匯率(client, fx, confirm_card, crawl):
    # Arrange：回放今日全幣別牌告——合法的 CSV，但沒有日圓的歷史牌告
    fx.wrong_shape = True
    confirm_card(client, LUCARIO)

    # Act
    result = crawl(client)

    # Assert：解析不出東西就是明確失敗，不是「這天沒有匯率」
    assert result["cards"][0]["quarantined"] == 20
    assert _market(client, LUCARIO_APPAREL) is None


def test_匯率來源連不上時成交仍以原幣入庫(client, fx, confirm_card, crawl):
    # Arrange
    fx.fails_with = "臺銀匯率請求失敗：連線中斷"
    confirm_card(client, LUCARIO)

    # Act
    result = crawl(client)

    # Assert：外部掛掉不會讓整個爬取失敗，原幣照樣進得來，等匯率通了再換算
    assert result["cards"][0]["inserted"] == 20
    assert result["cards"][0]["quarantined"] == 20
    assert _market(client, LUCARIO_APPAREL) is None


def test_英文版牌告也認得(client, fx, confirm_card, crawl):
    # Arrange：模擬 Chrome 時會連 Accept-Language: en-US 一起送，臺銀就回英文版
    fx.english = True
    confirm_card(client, LUCARIO)

    # Act
    crawl(client)

    # Assert：欄位位置與數值相同，只有方向欄的字不同——不該因此回報「沒有牌告」
    assert _market(client, LUCARIO_APPAREL)["market_value_twd"] == 1215


def test_匯率抓不到時爬取結果說得出原因(client, fx, confirm_card, crawl):
    # Arrange
    fx.bot_challenge = True
    confirm_card(client, LUCARIO)

    # Act
    result = crawl(client)

    # Assert：待審原因不能把外部故障說成資料問題
    assert result["fx"]["fetched"] is True
    assert result["fx"]["converted"] == 0
    assert "被機器人驗證擋下" in result["fx"]["error"]
    assert {sale["quarantine_reason"] for sale in _quarantine(client)} == {
        "匯率來源暫時不可用"
    }


def test_來源恢復後待審原因跟著更正(client, fx, confirm_card, crawl):
    # Arrange：這張卡的成交全在 2023～2025，早於臺銀六個月的涵蓋範圍
    fx.bot_challenge = True
    confirm_card(client, BEFORE_FX_RANGE)
    crawl(client)
    assert {sale["quarantine_reason"] for sale in _quarantine(client)} == {
        "匯率來源暫時不可用"
    }

    # Act：臺銀恢復正常
    fx.bot_challenge = False
    result = crawl(client)

    # Assert：這下確定不是外部故障，是那些日期真的沒有牌告
    assert result["fx"]["error"] is None
    assert {sale["quarantine_reason"] for sale in _quarantine(client)} == {
        "查無成交當日匯率"
    }


def test_被擋一次不會變成永久待審(client, fx, confirm_card, crawl):
    # Arrange：第一輪被機器人驗證擋下，20 筆全部待審
    fx.bot_challenge = True
    confirm_card(client, LUCARIO)
    crawl(client)
    assert _market(client, LUCARIO_APPAREL) is None

    # Act：臺銀恢復正常後再跑一輪
    fx.bot_challenge = False
    result = crawl(client)

    # Assert：暫時性的故障不會被固化成資料問題
    assert result["cards"][0]["quarantined"] == 0
    assert _market(client, LUCARIO_APPAREL)["market_value_twd"] == 1215
    assert _quarantine(client) == []
