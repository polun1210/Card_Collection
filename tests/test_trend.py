"""走勢圖的外部行為。

走勢圖回答的是「我的收藏整體在漲還是在跌」，而它必須是一張**可以被信任的紀錄**：
昨天截圖存下的圖，今天仍然對得上。這一組測試守的就是這件事——

- 每一天用**該日實際持有**的卡計算（ADR-0003），賣出一張卡不回頭改寫歷史。
- 每一天的市值只看**該日（含）以前**的成交紀錄，未來的成交不洩漏進過去。
- 每一個點都揭露涵蓋率，因為算得出市值的持有卡種數隨日期回推急遽衰減；不揭露
  的話，八月的爬升會被讀成行情暴漲（ADR-0021）。

斷言一律走 HTTP，不呼叫內部函式——重寫實作但行為不變時，測試不該紅。
"""

from datetime import UTC, datetime

from conftest import (
    BEFORE_FX_RANGE,
    LUCARIO,
    OLD_TRADES,
    PIKACHU_25TH,
    PRINTING_ERROR,
)

# 把時鐘撥到最後一筆成交的 55 天後，用來看「近 30 天無成交」在曲線上的樣子。
LATER = datetime(2026, 9, 30, tzinfo=UTC)

# 這幾張卡的成交紀錄形狀（取自既有測試的實測值）：
#   OLD_TRADES     20 筆，2026-03-09 – 2026-08-06，市值 374255
#   LUCARIO        20 筆，全部落在 2026-08-24 – 2026-08-25
#   BEFORE_FX_RANGE 7 筆，全部因查無成交當日匯率而待審，一筆都不參與計算
OLD_TRADES_FIRST_SALE = "2026-03-09"
OLD_TRADES_VALUE = 374255
LUCARIO_FIRST_SALE = "2026-08-24"
# 匯入的持有品裡最早的購入日。它晚於最早的成交紀錄，所以曲線從它起算。
FIRST_PURCHASE = "2026-03-15"
TODAY = "2026-08-26"


def _trend(client) -> list[dict]:
    response = client.get("/api/portfolio")
    assert response.status_code == 200, response.text
    return response.json()["trend"]


def _at(points: list[dict], day: str) -> dict:
    return next(point for point in points if point["date"] == day)


def _held_on(holding: dict, day: str) -> bool:
    """該日實際持有：購入日 ≤ 該日，且（未售出 或 售出日 > 該日）。"""
    return holding["purchase_date"] <= day and (
        holding["sold_date"] is None or holding["sold_date"] > day
    )


def _holdings(client) -> list[dict]:
    return client.get("/api/holdings").json()


def _kind_id(client, card: tuple) -> int:
    """卡種列 id。持有品掛在卡種列上（ADR-0012），新增時要指定它。"""
    return next(
        holding["mapping_candidate_id"]
        for holding in _holdings(client)
        if (holding["series_raw"], holding["number_raw"], holding["card_name_raw"])
        == card[:3]
    )


def _crawled(client, confirm_card, crawl):
    """把有錄到成交紀錄的卡種全部確認並跑一輪行情。"""
    for card in (LUCARIO, PRINTING_ERROR, OLD_TRADES, BEFORE_FX_RANGE, PIKACHU_25TH):
        confirm_card(client, card)
    crawl(client)


# --- 曲線的形狀 ---------------------------------------------------------


def test_曲線起點為成交紀錄與購入日兩者較晚者(client, confirm_card, crawl):
    # Arrange：最早成交在 2026-03-09，最早購入在 2026-03-15
    _crawled(client, confirm_card, crawl)

    # Act
    points = _trend(client)

    # Assert：一張卡都還沒買的那幾天兩條線都貼在 0，有寬度沒資訊
    assert points[0]["date"] == FIRST_PURCHASE
    assert points[0]["date"] > OLD_TRADES_FIRST_SALE
    assert points[-1]["date"] == TODAY


def test_曲線不從一張卡都沒持有的日子開始(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    points = _trend(client)

    # Assert
    assert points[0]["held_kind_count"] > 0


def test_一筆持有品都沒有時不編出一條曲線(client_factory, confirm_card, crawl, write_notion_csv):
    # Arrange：有成交紀錄，但一筆持有品都沒有
    empty = write_notion_csv()

    # Act
    with client_factory(csv_path=empty) as client:
        points = _trend(client)

    # Assert：沒有持有品就沒有總市值也沒有總成本，畫不出來就說畫不出來
    assert points == []


def test_曲線逐日連續沒有斷點(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    points = _trend(client)

    # Assert：包含沒有任何成交發生的日子
    days = [datetime.fromisoformat(point["date"]).date() for point in points]
    assert all(
        (later - earlier).days == 1 for earlier, later in zip(days, days[1:])
    )
    assert len(points) == 165


def test_沒有任何成交紀錄時不編出一條曲線(client):
    # Act：確認都還沒做，更不用說爬取
    points = _trend(client)

    # Assert：不為了填滿版面而畫一條線
    assert points == []


# --- 成本階梯線 ---------------------------------------------------------


def test_每一天的總成本等於該日實際持有的成本總和(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)
    holdings = _holdings(client)

    # Act
    points = _trend(client)

    # Assert
    for point in points:
        expected = sum(
            holding["cost_twd"]
            for holding in holdings
            if _held_on(holding, point["date"])
        )
        assert point["cost_twd"] == expected, point["date"]


def test_購入日當天成本線跳一階前一天不受影響(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)
    before = _trend(client)

    # Act：補登一筆五月的購入，不重新爬取
    response = client.post(
        "/api/holdings",
        json={
            "mapping_candidate_id": _kind_id(client, LUCARIO),
            "cost_twd": 9999,
            "purchase_date": "2026-05-10",
        },
    )
    assert response.status_code == 200, response.text
    after = _trend(client)

    # Assert：階梯的邊緣落在購入日當天，不是前一天也不是後一天
    assert _at(after, "2026-05-09")["cost_twd"] == _at(before, "2026-05-09")["cost_twd"]
    assert (
        _at(after, "2026-05-10")["cost_twd"]
        == _at(before, "2026-05-10")["cost_twd"] + 9999
    )
    assert _at(after, TODAY)["cost_twd"] == _at(before, TODAY)["cost_twd"] + 9999


def test_賣出一張卡之後售出日之前的資料點完全不變(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)
    before = _trend(client)
    holding = next(
        holding
        for holding in _holdings(client)
        if holding["status"] == "held" and holding["purchase_date"] < "2026-04-01"
    )

    # Act
    response = client.post(
        f"/api/holdings/{holding['id']}/sale",
        json={"sold_price_twd": 30000, "sold_date": "2026-06-15"},
    )
    assert response.status_code == 200, response.text
    after = _trend(client)

    # Assert：昨天截圖存下的圖，今天仍然對得上（ADR-0003）
    for earlier, later in zip(before, after):
        if earlier["date"] < "2026-06-15":
            assert earlier == later, earlier["date"]
    # 而售出日當天起，那張卡就不再是「該日實際持有」
    assert (
        _at(after, "2026-06-15")["cost_twd"]
        == _at(before, "2026-06-15")["cost_twd"] - holding["cost_twd"]
    )


def test_走勢圖逐日即時計算不倚賴快照(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)
    before = _trend(client)
    holding = next(
        holding
        for holding in _holdings(client)
        if holding["purchase_date"] < "2026-04-01"
    )

    # Act：刪掉一筆記錯的持有品，不重新爬取
    assert client.delete(f"/api/holdings/{holding['id']}").status_code == 200
    after = _trend(client)

    # Assert：沒有任何快照表擋在中間，歷史當場跟著更正
    assert (
        _at(after, "2026-04-01")["cost_twd"]
        == _at(before, "2026-04-01")["cost_twd"] - holding["cost_twd"]
    )


# --- 市值曲線 -----------------------------------------------------------


def test_某一天的市值不受該日之後才發生的成交影響(client, confirm_card, crawl):
    # Arrange：先只讓 S-P 144 有成交紀錄，曲線從 2026-03-09 起算
    confirm_card(client, OLD_TRADES)
    crawl(client)
    before = _trend(client)

    # Act：再加入一張成交全部落在 8/24–8/25 的卡
    confirm_card(client, LUCARIO)
    crawl(client)
    after = _trend(client)

    # Assert：8/24 以前的每一個點一字未改——未來的成交不會洩漏進過去
    for earlier, later in zip(before, after):
        if earlier["date"] < LUCARIO_FIRST_SALE:
            assert earlier == later, earlier["date"]
    assert _at(after, LUCARIO_FIRST_SALE) != _at(before, LUCARIO_FIRST_SALE)


def test_近30天無成交的卡種在曲線上沿用最後算得出的市值(
    client_factory, confirm_card, crawl
):
    # Arrange：這張卡最新的成交在 2026-08-06，且只有一張持有中
    with client_factory() as client:
        confirm_card(client, OLD_TRADES)
        crawl(client)

    # Act：把時鐘撥到 55 天後
    with client_factory(now=LATER) as later:
        points = _trend(later)

    # Assert：曲線不會突然斷掉或掉到零，沿用的是最後一次算得出的市值
    assert points[-1]["date"] == "2026-09-30"
    assert points[-1]["market_value_twd"] == OLD_TRADES_VALUE
    assert points[-1]["valued_kind_count"] == 1


def test_沒有市值的卡種計入持有卡種數但不進總市值(client, confirm_card, crawl):
    # Arrange：這張卡的成交全部因為查無成交當日匯率而待審
    confirm_card(client, OLD_TRADES)
    confirm_card(client, BEFORE_FX_RANGE)
    crawl(client)

    # Act
    point = _at(_trend(client), TODAY)

    # Assert：算不出市值的卡種不會被靜默忽略，也不會被填上編出來的數字
    assert point["valued_kind_count"] == 1
    assert point["held_kind_count"] > point["valued_kind_count"]
    assert point["market_value_twd"] == OLD_TRADES_VALUE


def test_曲線最後一天與持有品摘要對得起來(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)
    summary = client.get("/api/holdings/summary").json()

    # Act
    point = _at(_trend(client), TODAY)

    # Assert：走勢圖不是第二套帳。今天這個點與摘要都是「現在持有的卡值多少」，
    # 兩者對不起來就表示曲線的終點在說另一個故事。
    assert point["cost_twd"] == summary["held_cost_twd"]
    assert point["market_value_twd"] == summary["held_market_value_twd"]


# --- 涵蓋率 -------------------------------------------------------------


def test_每個資料點都附上算得出市值與總持有的卡種數(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    points = _trend(client)

    # Assert
    for point in points:
        assert set(point) == {
            "date",
            "market_value_twd",
            "cost_twd",
            "valued_kind_count",
            "held_kind_count",
        }
        assert 0 <= point["valued_kind_count"] <= point["held_kind_count"]


def test_涵蓋率與該日實際算得出市值的卡種數一致(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)
    held = [holding for holding in _holdings(client) if holding["status"] == "held"]

    # Act
    point = _at(_trend(client), TODAY)

    # Assert：與逐筆持有品端點算出來的是同一件事，不是另一套帳
    def kinds(rows) -> set:
        return {
            (row["series_raw"], row["number_raw"], row["card_name_raw"])
            for row in rows
        }

    assert point["held_kind_count"] == len(kinds(held))
    assert point["valued_kind_count"] == len(
        kinds(holding for holding in held if "market_value_twd" in holding)
    )


def test_涵蓋率隨日期回推而衰減(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    points = _trend(client)

    # Assert：這正是逐日揭露涵蓋率存在的理由——不揭露的話，八月的爬升會被讀成
    # 行情暴漲，而它其實有一半是資料涵蓋率補齊造成的。
    assert points[0]["valued_kind_count"] < points[-1]["valued_kind_count"]


# --- 首頁畫面 -----------------------------------------------------------


def test_首頁畫出走勢圖而不是留一個佔位方塊(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert
    assert "資產走勢" in html
    assert "<svg" in html
    assert "總成本" in html


def test_走勢圖不引入圖表函式庫(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：內嵌 SVG 自己畫，不從外面載任何東西進來
    assert "<script src=" not in html
    assert "cdn." not in html


def test_首頁提供四個時間區間且沒有1D(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：每日爬取的系統給不出日內走勢，提供 1D 只會製造錯誤期待
    for label in ("7D", "1M", "3M", "ALL"):
        assert f">{label}<" in html
    assert ">1D<" not in html


def test_資料不足一年時不顯示YTD(client, confirm_card, crawl):
    # Arrange：這批資料自 2026-03-09 起算，總跨度 171 天
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：不讓人點到一個與 ALL 完全一樣的區間
    assert ">YTD<" not in html


def test_首頁揭露當天的涵蓋率(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)
    point = _at(_trend(client), TODAY)

    # Act
    html = client.get("/").text

    # Assert：涵蓋率是必要的，不是裝飾
    assert "涵蓋率" in html
    assert f"{point['valued_kind_count']} / {point['held_kind_count']}" in html


def test_沒有曲線可畫時說明在等什麼(client):
    # Act
    html = client.get("/").text

    # Assert：空白會被讀成「壞掉了」
    assert "資產走勢" in html
    assert "畫不出曲線" in html
