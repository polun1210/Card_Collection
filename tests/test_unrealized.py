"""未實現損益的外部行為。

未實現損益（持有中）與已實現損益（已售出）永遠分開，永不混入同一個數字。
沒有市值的持有品不長出損益欄位——0 會被讀成「不賺不賠」。
"""

from datetime import UTC, datetime

from conftest import BEFORE_FX_RANGE, LUCARIO, OLD_TRADES, PIKACHU_25TH, PRINTING_ERROR

LATER = datetime(2026, 9, 30, tzinfo=UTC)

LUCARIO_VALUE = 1215
PRINTING_ERROR_VALUE = 5626
OLD_TRADES_VALUE = 374255

LUCARIO_COSTS = (2400, 2600, 2650)
PRINTING_ERROR_COST = 12500
OLD_TRADES_COST = 15800

# 有市值的持有中持有品：MEGA Lucario 三張、錯體版一張、S-P 144 一張。
VALUED_COUNT = 5
HELD_MARKET_VALUE = 3 * LUCARIO_VALUE + PRINTING_ERROR_VALUE + OLD_TRADES_VALUE
VALUED_COST = sum(LUCARIO_COSTS) + PRINTING_ERROR_COST + OLD_TRADES_COST
UNREALIZED_PNL = HELD_MARKET_VALUE - VALUED_COST
REALIZED_PNL_TWD = 86_108
HELD_COUNT = 89


def _holdings(client) -> list[dict]:
    response = client.get("/api/holdings")
    assert response.status_code == 200, response.text
    return response.json()


def _summary(client) -> dict:
    response = client.get("/api/holdings/summary")
    assert response.status_code == 200, response.text
    return response.json()


def _of_kind(client, card: tuple) -> list[dict]:
    return [
        holding
        for holding in _holdings(client)
        if (holding["series_raw"], holding["number_raw"], holding["card_name_raw"])
        == card[:3]
    ]


def _crawled(client, confirm_card, crawl):
    """把有錄到成交紀錄的卡種全部確認並跑一輪行情。"""
    for card in (LUCARIO, PRINTING_ERROR, OLD_TRADES, BEFORE_FX_RANGE, PIKACHU_25TH):
        confirm_card(client, card)
    crawl(client)


# --- 逐筆 ---------------------------------------------------------------


def test_持有中的持有品帶有未實現損益(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    lucarios = _of_kind(client, LUCARIO)

    # Assert：每一張各自與自己的購入成本比，不做平均成本
    assert sorted(holding["unrealized_pnl_twd"] for holding in lucarios) == sorted(
        LUCARIO_VALUE - cost for cost in LUCARIO_COSTS
    )


def test_持有中的持有品帶有報酬率(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    holding = _of_kind(client, OLD_TRADES)[0]

    # Assert：報酬率一律是 (結果 − 成本) ÷ 成本，與已實現損益同一個定義
    assert holding["return_rate"] == (
        OLD_TRADES_VALUE - OLD_TRADES_COST
    ) / OLD_TRADES_COST


def test_持有品同時帶著成本與市值(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    holding = _of_kind(client, PRINTING_ERROR)[0]

    # Assert：不必自己心算
    assert holding["cost_twd"] == PRINTING_ERROR_COST
    assert holding["market_value_twd"] == PRINTING_ERROR_VALUE
    assert holding["unrealized_pnl_twd"] == PRINTING_ERROR_VALUE - PRINTING_ERROR_COST


def test_沒有市值的卡種其持有品不出現損益欄位(client, confirm_card, crawl):
    # Arrange：這張卡的成交全部因為查無匯率而待審
    _crawled(client, confirm_card, crawl)

    # Act
    holding = _of_kind(client, BEFORE_FX_RANGE)[0]

    # Assert：缺資料不會被讀成不賺不賠
    assert "market_value_twd" not in holding
    assert "unrealized_pnl_twd" not in holding
    assert "return_rate" not in holding


def test_已售出的持有品不因為有了市值就冒出未實現損益(client, confirm_card, crawl):
    # Arrange：這個卡種兩張都已售出，且它有市值
    _crawled(client, confirm_card, crawl)

    # Act
    sold = _of_kind(client, PIKACHU_25TH)

    # Assert：終局的數字維持終局
    assert len(sold) == 2
    assert all(holding["status"] == "sold" for holding in sold)
    assert all("unrealized_pnl_twd" not in holding for holding in sold)
    assert all(holding["realized_pnl_twd"] for holding in sold)


# --- 合計 ---------------------------------------------------------------


def test_全站持有中的總市值(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    summary = _summary(client)

    # Assert
    assert summary["held_market_value_twd"] == HELD_MARKET_VALUE


def test_全站未實現損益合計(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    summary = _summary(client)

    # Assert
    assert summary["unrealized_pnl_twd"] == UNREALIZED_PNL


def test_未實現損益與已實現損益分開呈現(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    summary = _summary(client)

    # Assert：賣掉賺的錢不會被算進「我現在的卡值多少」
    assert summary["realized_pnl_twd"] == REALIZED_PNL_TWD
    assert summary["unrealized_pnl_twd"] != summary["realized_pnl_twd"]
    assert summary["held_market_value_twd"] == HELD_MARKET_VALUE


def test_合計附上它涵蓋了幾張持有品(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    summary = _summary(client)

    # Assert：總市值不會被讀成已經涵蓋全部 89 張
    assert summary["valued_count"] == VALUED_COUNT
    assert summary["unvalued_count"] == HELD_COUNT - VALUED_COUNT
    assert summary["held_cost_valued_twd"] == VALUED_COST


# --- 畫面 ---------------------------------------------------------------


def test_持有品頁面同時顯示成本市值與未實現損益(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    page = client.get("/holdings")

    # Assert
    assert page.status_code == 200
    assert "持有中總市值" in page.text
    assert "未實現損益" in page.text
    assert f"{HELD_MARKET_VALUE:,}" in page.text
    assert f"{UNREALIZED_PNL:+,}" in page.text


def test_持有品頁面標出還有幾張沒有市值(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    page = client.get("/holdings")

    # Assert
    assert f"還有 {HELD_COUNT - VALUED_COUNT} 張沒有市值" in page.text


def test_持有品頁面標出市值的樣本期間(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    page = client.get("/holdings")

    # Assert：使用者看得出這個中位數實際上代表多長的時間
    assert "20 筆／2026-08-24～2026-08-25" in page.text


def test_市值過期的卡種在畫面上看得出來(client_factory, confirm_card, crawl):
    # Arrange
    with client_factory() as client:
        confirm_card(client, OLD_TRADES)
        crawl(client)

    # Act：把時鐘撥到 55 天後
    with client_factory(now=LATER) as later:
        page = later.get("/holdings")

    # Assert：不會把三個月前的價格當成今天的價格
    assert "已過期 55 天" in page.text
