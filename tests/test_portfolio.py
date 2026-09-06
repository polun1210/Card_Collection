"""Portfolio 首頁的外部行為。

首頁是「打開就看到自己的收藏」，不是後台工具——待審佇列因此搬到 `/queue`，功能
一字不改。走勢圖的行為在 test_trend.py、卡圖牆的行為在 test_card_wall.py，本檔只
保證這一頁的**總計數字**與**行情新鮮度**是真的。

總計數字不重算一份：首頁與持有品頁必須逐欄一致，否則同一批持有品會有兩套帳。
"""

from datetime import timedelta

import pytest
from conftest import (
    BEFORE_FX_RANGE,
    DEFAULT_NOW,
    LUCARIO,
    OLD_TRADES,
    PIKACHU_25TH,
    PRINTING_ERROR,
)

# 與 test_unrealized.py 同一組實測值。刻意重寫而非跨檔匯入——這幾個數字是本檔
# 自己的預期，跟著別的測試檔一起漂移的話，壞掉時看不出是誰動了誰。
LUCARIO_VALUE = 1215
PRINTING_ERROR_VALUE = 5626
OLD_TRADES_VALUE = 374255
VALUED_COST = (2400 + 2600 + 2650) + 12500 + 15800
HELD_MARKET_VALUE = 3 * LUCARIO_VALUE + PRINTING_ERROR_VALUE + OLD_TRADES_VALUE
UNREALIZED_PNL = HELD_MARKET_VALUE - VALUED_COST
REALIZED_PNL_TWD = 86_108


def _portfolio(client) -> dict:
    response = client.get("/api/portfolio")
    assert response.status_code == 200, response.text
    return response.json()


def _hero(html: str) -> str:
    """截出 Hero 那一片。走勢與持有摘要在同一個 <section class="hero"> 裡（#31），
    卡圖牆的「已售出」分頁、卡片明細裡的「未實現損益」都在這片之外，不該混進來。"""
    start = html.index('<section class="hero">')
    return html[start : html.index("</section>", start)]


def _crawled(client, confirm_card, crawl):
    """把有錄到成交紀錄的卡種全部確認並跑一輪行情。"""
    for card in (LUCARIO, PRINTING_ERROR, OLD_TRADES, BEFORE_FX_RANGE, PIKACHU_25TH):
        confirm_card(client, card)
    crawl(client)


# --- 路由 ---------------------------------------------------------------


def test_根路徑是收藏總覽而不是待審佇列(client):
    # Act
    html = client.get("/").text

    # Assert：意圖是「根路徑給的是收藏儀表板，不是後台的待審佇列」
    # （docs/interface.md §2）。原本用「卡種對應」當代理字串，但 ADR-0023 的
    # 全站頁首讓它出現在每一頁，不再能代表待審佇列，改用佇列工作區的專屬標記。
    assert "SNKRDUNK 候選" not in html
    # 成對驗證：確認這個標記在待審佇列頁確實存在，否則上面那條會空洞地為真
    assert "SNKRDUNK 候選" in client.get("/queue").text


def test_待審佇列搬到queue後功能不變(client, confirm_card):
    # Arrange
    # 已確認的卡種區塊要有東西才長得出來，光看得到頁面不算「功能不變」。
    confirm_card(client, LUCARIO)

    # Act
    response = client.get("/queue")

    # Assert
    assert response.status_code == 200, response.text
    assert "卡種對應" in response.text
    assert "下載對照清單 CSV" in response.text
    assert "MEGA Lucario" in response.text


def test_待審佇列的批次大小參數在新路徑上仍然有效(client):
    # Act
    response = client.get("/queue", params={"limit": 14})

    # Assert
    assert response.status_code == 200, response.text


def test_持有品頁不受首頁改動影響(client):
    # Act
    response = client.get("/holdings")

    # Assert
    assert response.status_code == 200, response.text
    assert "持有品" in response.text


# --- 端點 ---------------------------------------------------------------


def test_portfolio端點回傳總計與行情新鮮度(client):
    # Act
    body = _portfolio(client)

    # Assert
    # 只查這兩塊在不在。首頁要的一切一次拿齊，這個回應會隨著卡圖牆、走勢圖繼續長，
    # 逐字比對整組 key 只會讓每張新票都來改這一行。
    assert {"summary", "freshness"} <= set(body)


def test_首頁總計與持有品摘要端點逐欄一致(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    summary = _portfolio(client)["summary"]
    reference = client.get("/api/holdings/summary").json()

    # Assert
    # 首頁只補一個報酬率，其餘每一欄都必須是同一個來源算出來的同一個值。
    for field, value in reference.items():
        assert summary[field] == value, field


def test_未實現損益與已實現損益是兩個欄位(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    summary = _portfolio(client)["summary"]

    # Assert
    assert summary["unrealized_pnl_twd"] == UNREALIZED_PNL
    assert summary["realized_pnl_twd"] == REALIZED_PNL_TWD


def test_已實現損益總額不因換首頁而改變(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    summary = _portfolio(client)["summary"]

    # Assert
    assert summary["realized_pnl_twd"] == REALIZED_PNL_TWD


def test_報酬率只用有市值的成本當分母(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    summary = _portfolio(client)["summary"]

    # Assert
    assert summary["unrealized_return_rate"] == pytest.approx(
        UNREALIZED_PNL / VALUED_COST
    )
    # 分母若含沒有市值的那些持有品，報酬率會被稀釋成一個誰也不代表的數字。
    assert summary["held_cost_twd"] > VALUED_COST
    assert summary["unrealized_return_rate"] != pytest.approx(
        UNREALIZED_PNL / summary["held_cost_twd"]
    )


def test_沒有市值時不長出報酬率(client):
    # Act
    summary = _portfolio(client)["summary"]

    # Assert
    # 缺的數字就讓欄位不存在——0 會被讀成「不賺不賠」。
    assert summary["valued_count"] == 0
    assert "unrealized_return_rate" not in summary


# --- 首頁畫面（Hero，#31）--------------------------------------------------


def test_Hero是一整片版面而不是兩張卡片(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：資產走勢與持有摘要在同一個 <section class="hero"> 裡（spec §7.3）
    assert '<section class="hero">' in html
    hero = _hero(html)
    assert "資產走勢" in hero
    assert "持有中總市值" in hero


def test_持有中總市值是Hero裡最大的金額(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    hero = _hero(client.get("/").text)

    # Assert：最大的字級（.hero-value）只出現一次，且落在持有中總市值上（spec §7.3）
    assert hero.count("hero-value") == 1
    label_at = hero.index("持有中總市值")
    value_at = hero.index("hero-value")
    assert value_at - label_at < 120, "hero-value 緊接在『持有中總市值』標籤之後"
    assert f"{HELD_MARKET_VALUE:,}" in hero


def test_Hero不出現已實現損益與已售出張數(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    hero = _hero(client.get("/").text)

    # Assert：已實現損益是已售出的事，不進 Hero；已售出張數同理（spec §7.3）
    assert "已實現損益" not in hero
    assert "已售出" not in hero
    assert f"{REALIZED_PNL_TWD:,}" not in hero


def test_Hero顯示未實現損益與報酬率(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    hero = _hero(client.get("/").text)

    # Assert：未實現損益與報酬率講的是「持有中的部位現在賺賠多少」，留在 Hero
    assert "未實現損益" in hero
    assert "報酬率" in hero
    assert f"{UNREALIZED_PNL:+,}" in hero


def test_走勢圖下方沒有教學段落(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：改版改用圖上標籤自我說明，移除圖下方那段解釋兩條線與涵蓋率的教學文字
    assert "把游標移到曲線上" not in html
    assert '<p class="hint">' not in html


def test_摘要在DOM裡排在走勢圖之前(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    hero = _hero(client.get("/").text)

    # Assert：手機直向堆疊時最重要的數字不必先捲過一張圖（spec §11.2）。桌機靠
    # CSS row-reverse 把摘要視覺上移到右側——所以 DOM 順序是這個行為的唯一依據，
    # 換掉 row-reverse 又不調 DOM 的話手機會悄悄壞掉。
    assert hero.index("持有中總市值") < hero.index("資產走勢")


def test_還沒有走勢資料時不謊報卡種數(client):
    # Act：還沒爬過任何成交紀錄，trend 是空的，卡種數沒有來源
    hero = _hero(client.get("/").text)

    # Assert：省略是誠實的，寫「0 卡種」不是——持有 89 張卻寫 0 卡種會被讀成
    # 「我一個卡種都沒有」（同 §7.7 用破折號而不是 0.0% 的道理）
    assert "0 卡種" not in hero


def test_首頁顯示還有幾張缺市值(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert
    # 總市值若沒說清楚只涵蓋幾張，會被讀成已經涵蓋全部。
    summary = _portfolio(client)["summary"]
    assert summary["unvalued_count"] > 0
    assert f"{summary['unvalued_count']} 張沒有市值" in html


def test_從未成功爬取時首頁顯示警示(client):
    # Act
    html = client.get("/").text

    # Assert
    assert "從未成功更新過行情" in html


def test_剛爬完首頁不出現行情警示(client, confirm_card, crawl):
    # Arrange
    confirm_card(client, LUCARIO)
    crawl(client)

    # Act
    html = client.get("/").text

    # Assert：行情健康時不顯示新鮮度橫幅（uiux-spec §7.2）。interface.md §5 第 6 條
    # 「新鮮度必須與市值同畫面」防的是「過期時被誤導」——新設計過期會大聲警示
    # （見 test_超過24小時首頁顯示過期警示），意圖保住；健康時隱藏只是少了
    # 「幾小時前」的資訊，不是誠實性問題。
    assert "從未成功更新過行情" not in html
    assert "已超過 24 小時沒有成功更新" not in html
    assert 'class="freshness' not in html


def test_超過24小時首頁顯示過期警示(client_factory, confirm_card, crawl):
    # Arrange
    with client_factory() as client:
        confirm_card(client, LUCARIO)
        crawl(client)

    # Act
    with client_factory(now=DEFAULT_NOW + timedelta(hours=25)) as later:
        html = later.get("/").text

    # Assert
    assert "已超過 24 小時沒有成功更新" in html


def test_首頁可以觸發一次手動爬取(client):
    # Act
    html = client.get("/").text

    # Assert
    assert "更新行情" in html
    assert "/api/market/crawl" in html
