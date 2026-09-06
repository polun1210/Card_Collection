"""動能與流動性的外部行為。

動能維持**成交價中位數**的定義（CONTEXT.md、ADR-0002 的同一把尺）：近 30 天成交
紀錄的中位數，相對前 30 天（第 31–60 天）的中位數，取報酬率。兩個視窗任一為空就
不算——不回 0，也不回 null。0 會被讀成「不漲不跌」，那是騙人的。

流動性恆為不可用：PSA 10 張數尚未實作、熱門度受 20 筆上限低估，而兩者分開看沒有
意義，必須並列，因此不先開其中一半。

這兩個空狀態不是暫時的鷹架：新買進的卡種永遠會經歷「還沒有動能」的階段。
"""

from datetime import timedelta
from statistics import median

import pytest
from conftest import DEFAULT_NOW, LUCARIO, OLD_TRADES, PRINTING_ERROR

# 實測值。錯體版在 fixture 錄製當下正在跌：兩個視窗都有成交，中位數由 7553.5 掉到
# 5625.5。刻意寫死而不在測試裡重算——重算一遍就是把實作抄進測試裡。
PRINTING_ERROR_RECENT = (5386, 5538, 5538, 5611, 5640, 5838, 6534, 6557)
PRINTING_ERROR_PREVIOUS = (6868, 7096, 7270, 7440, 7475, 7632, 7671, 7683, 7852, 7868)


def _indicators(client, apparel_id: int) -> dict:
    """動能與流動性掛在**既有的**卡種持有品端點上，本票不新增接縫。"""
    response = client.get(f"/api/cards/{apparel_id}/holdings")
    assert response.status_code == 200, response.text
    return response.json()


def _momentum(client, apparel_id: int) -> dict:
    return _indicators(client, apparel_id)["momentum"]


def _rate(recent, previous) -> float:
    return (median(recent) - median(previous)) / median(previous)


# --- 動能算得出來的時候 -------------------------------------------------


def test_動能是兩個視窗成交價中位數的報酬率(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    momentum = _momentum(client, PRINTING_ERROR[3])

    # Assert
    assert momentum["available"] is True
    assert momentum["return_rate"] == pytest.approx(
        _rate(PRINTING_ERROR_RECENT, PRINTING_ERROR_PREVIOUS)
    )


def test_動能用中位數而不是平均(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    momentum = _momentum(client, PRINTING_ERROR[3])

    # Assert：定義維持成交價中位數，未改為其他定義
    mean_recent = sum(PRINTING_ERROR_RECENT) / len(PRINTING_ERROR_RECENT)
    mean_previous = sum(PRINTING_ERROR_PREVIOUS) / len(PRINTING_ERROR_PREVIOUS)
    average_rate = (mean_recent - mean_previous) / mean_previous
    assert momentum["return_rate"] != pytest.approx(average_rate)


def test_動能附上兩個視窗各自的成交筆數(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    momentum = _momentum(client, PRINTING_ERROR[3])

    # Assert：兩筆撐起來的 −25% 與二十筆撐起來的 −25% 不該長得一模一樣
    assert momentum["recent_count"] == len(PRINTING_ERROR_RECENT)
    assert momentum["previous_count"] == len(PRINTING_ERROR_PREVIOUS)


def test_動能是報酬率而不是倍數(client, confirm_card, crawl):
    # Arrange：這張卡在跌，報酬率為負；倍數永遠是正的，兩者分得出來
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    momentum = _momentum(client, PRINTING_ERROR[3])

    # Assert：全站唯一的報酬率定義是 (結果 − 成本) ÷ 成本
    assert momentum["return_rate"] < 0
    assert momentum["return_rate"] != pytest.approx(
        median(PRINTING_ERROR_RECENT) / median(PRINTING_ERROR_PREVIOUS)
    )


def test_成交稀疏的卡種照樣算得出動能(client, confirm_card, crawl):
    # Arrange：這張卡兩個視窗各只有三筆與兩筆
    confirm_card(client, OLD_TRADES)
    crawl(client)

    # Act
    momentum = _momentum(client, OLD_TRADES[3])

    # Assert：樣本少不等於算不出來，樣本少這件事由筆數自己說
    assert momentum["available"] is True
    assert (momentum["recent_count"], momentum["previous_count"]) == (3, 2)


# --- 動能算不出來的時候 -------------------------------------------------


def test_近30天無成交時動能不可用並說出理由(client_factory, confirm_card, crawl):
    # Arrange：把「今天」往後推 40 天，最後一筆成交落到近 30 天之外
    with client_factory() as client:
        confirm_card(client, LUCARIO)
        crawl(client)

    # Act
    with client_factory(now=DEFAULT_NOW + timedelta(days=40)) as later:
        momentum = _momentum(later, LUCARIO[3])

    # Assert
    assert momentum["available"] is False
    assert "近 30 天" in momentum["reason"]


def test_前30天無成交時動能不可用並說出理由(client, confirm_card, crawl):
    # Arrange：這張卡的成交全擠在最近兩天，第 31–60 天一筆都沒有
    confirm_card(client, LUCARIO)
    crawl(client)

    # Act
    momentum = _momentum(client, LUCARIO[3])

    # Assert：沒有可比的基準就不比，不拿別的期間硬湊
    assert momentum["available"] is False
    assert "第 31–60 天" in momentum["reason"]


@pytest.mark.parametrize("days_later", [0, 40])
def test_動能不可用時不回0也不回null(client_factory, confirm_card, crawl, days_later):
    # Arrange：兩種空狀態各測一次
    with client_factory() as client:
        confirm_card(client, LUCARIO)
        crawl(client)

    # Act
    with client_factory(now=DEFAULT_NOW + timedelta(days=days_later)) as later:
        momentum = _momentum(later, LUCARIO[3])

    # Assert：0 會被讀成「不漲不跌」，null 會被讀成「壞了」，兩者都是騙人的
    assert momentum is not None
    assert "return_rate" not in momentum
    assert momentum["reason"]


def test_從未抓到成交的卡種動能不可用(client, confirm_card):
    # Arrange：確認了對應，但還沒跑過任何一輪行情
    confirm_card(client, LUCARIO)

    # Act
    momentum = _momentum(client, LUCARIO[3])

    # Assert
    assert momentum["available"] is False
    assert "return_rate" not in momentum


def test_不放寬視窗去湊資料(client_factory, confirm_card, crawl):
    # Arrange：把「今天」推到兩個視窗都空掉
    with client_factory() as client:
        confirm_card(client, LUCARIO)
        crawl(client)

    # Act
    with client_factory(now=DEFAULT_NOW + timedelta(days=70)) as later:
        momentum = _momentum(later, LUCARIO[3])

    # Assert：放寬窗口會讓「動能」變成一個浮動的定義
    assert momentum["available"] is False


# --- 流動性 -------------------------------------------------------------


def test_流動性恆為不可用且帶理由(client, confirm_card, crawl):
    # Arrange：連成交紀錄最齊全的卡種也一樣
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    liquidity = _indicators(client, PRINTING_ERROR[3])["liquidity"]

    # Assert
    assert liquidity["available"] is False
    assert liquidity["reason"]


def test_流動性不先開熱門度一半(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    liquidity = _indicators(client, PRINTING_ERROR[3])["liquidity"]

    # Assert：兩個半邊都要說明，且都不給數字——存世多但成交少，與存世多且成交多，
    # 是完全不同的兩張卡
    assert "PSA 10 張數" in liquidity["reason"]
    assert "熱門度" in liquidity["reason"]
    assert "popularity_count" not in liquidity
    assert "psa10_population" not in liquidity


# --- 接縫 ---------------------------------------------------------------


def test_動能與流動性掛在既有的卡種持有品端點(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    body = _indicators(client, PRINTING_ERROR[3])

    # Assert：同一支端點一併回來，展開卡片不必打第二次
    assert {"holdings", "summary", "market_value", "momentum", "liquidity"} <= set(body)


def test_卡圖牆的列表回應不背負動能(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    wall = client.get("/api/portfolio").json()["wall"]

    # Assert：動能是展開時才取的，列表不為了它多算 68 次
    assert all("momentum" not in cell for cell in wall["held"] + wall["sold"])


# --- 畫面 ---------------------------------------------------------------


def _page(client) -> str:
    return client.get("/").text


def test_抽屜的市場區有動能與流動性(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act：抽屜內容 server-render 在每格的 <template> 裡，仍在 HTML 原始碼中
    page = _page(client)

    # Assert：抽屜殼在，市場區的兩個指標都在
    assert 'id="card-drawer"' in page
    assert "動能" in page
    assert "流動性" in page


def test_流動性在抽屜裡是敬請期待並說出兩個半邊(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    page = _page(client)

    # Assert：流動性一筆都還沒在收（PriceCharting 未實作），所以是「敬請期待」而不是
    # 「資料累積中」——後者會讓畫面說「資料正在累積」，那是第一層的謊。兩個半邊
    # （PSA 10 張數＋近 3 月成交）永遠並列。
    assert 'id="card-drawer"' in page
    assert "敬請期待" in page
    assert "PSA 10 張數" in page
    assert "近 3 月成交" in page


def test_動能的空狀態在抽屜裡叫資料累積中(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    page = _page(client)

    # Assert：動能的來源存在、逐日累積，總有一天算得出來——「資料累積中」是誠實的
    assert 'id="card-drawer"' in page
    assert "資料累積中" in page


def test_動能與流動性的空狀態用共用的中性樣式(client, confirm_card, crawl):
    # 意圖不變：兩個未就緒狀態看起來像刻意留的位子，不是一塊沒渲染的空白。#33 之後
    # 改用共用的 .status-pending（design.css），不再是卡圖牆自己的 .soon。驗**渲染
    # 出來的 HTML** 用了這個 class，不驗 design.css 的內容——那是共用層、不是這張
    # 票擁有的檔案，去斷言它日後調整會讓這張票無故變紅。
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    page = _page(client)

    # Assert
    assert 'class="status-pending">資料累積中' in page
    assert 'class="status-pending">敬請期待' in page


def test_動能是打開明細那一刻才取而不隨牆面一起算(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, PRINTING_ERROR)
    crawl(client)

    # Act
    page = _page(client)
    momentum = _momentum(client, PRINTING_ERROR[3])

    # Assert：算好的動能不在首頁 HTML 裡（陪站崗的 in：佔位的「資料累積中」在，
    # 證明抽屜的動能區確實渲染了、只是還沒填值），它由打開明細那一刻的請求帶回來
    assert "資料累積中" in page
    assert f"{momentum['return_rate']:+.1%}" not in page
