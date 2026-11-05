"""卡圖牆的外部行為。

首頁下半用**認圖**的方式找卡：一格一個卡種，分持有中與已售出兩個分頁。同一個卡種
可以同時出現在兩邊——賣掉兩張、還持有三張是正常狀態，不是錯誤。

金額不重算一份：每一格的數字都由持有品摘要算出，與全站總計同一套帳。
"""

import re
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

# 與 test_unrealized.py 同一組實測值，刻意重寫而非跨檔匯入。
LUCARIO_VALUE = 1215
LUCARIO_COSTS = (2400, 2600, 2650)

# 同時有持有中與已售出的卡種：三張持有中、兩張已售出。
MEW = ("S12a", "183", "Mew")
MEW_HELD_COSTS = (3710, 3710, 3700)

# 已售出的兩張，各自與自己的成本比。
PIKACHU_25TH_COST = 39000 + 49440
PIKACHU_25TH_REALIZED = (57000 - 39000) + (60000 - 49440)


def _crawled(client, confirm_card, crawl):
    """把有錄到成交紀錄的卡種全部確認並跑一輪行情。"""
    for card in (LUCARIO, PRINTING_ERROR, OLD_TRADES, BEFORE_FX_RANGE, PIKACHU_25TH):
        confirm_card(client, card)
    crawl(client)


def _wall(client) -> dict:
    response = client.get("/api/portfolio")
    assert response.status_code == 200, response.text
    return response.json()["wall"]


def _identity(cell: dict) -> tuple:
    return (cell["series_raw"], cell["number_raw"], cell["card_name_raw"])


def _cell(cells: list[dict], card: tuple) -> dict:
    return next(cell for cell in cells if _identity(cell) == card[:3])


# --- 兩個分頁 -----------------------------------------------------------


def test_卡圖牆分成持有中與已售出兩組(client):
    # Act
    wall = _wall(client)

    # Assert
    assert set(wall) == {"held", "sold"}


def test_一格一個卡種而不是一格一張持有品(client):
    # Act
    held = _wall(client)["held"]

    # Assert：MEGA Lucario 持有三張，牆上只佔一格
    assert len({_identity(cell) for cell in held}) == len(held)
    assert _cell(held, LUCARIO)["held_count"] == 3


def test_同一卡種同時有持有中與已售出時兩個分頁都出現它(client):
    # Act
    wall = _wall(client)

    # Assert：賣掉兩張、還持有三張是正常狀態
    assert _cell(wall["held"], MEW)["held_count"] == 3
    assert _cell(wall["sold"], MEW)["sold_count"] == 2


# --- 排序 ---------------------------------------------------------------


def test_持有中依市值由高到低排序(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    held = _wall(client)["held"]

    # Assert：最貴的卡先進入視線
    values = [cell.get("held_market_value_twd", 0) for cell in held]
    assert values == sorted(values, reverse=True)
    assert _identity(held[0]) == OLD_TRADES[:3]


def test_沒有市值的卡種仍然出現在持有中(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    held = _wall(client)["held"]

    # Assert：不會憑空消失讓人以為少了一張卡
    cell = _cell(held, MEW)
    assert cell["held_count"] == 3
    # 缺的數字就讓欄位不存在——0 會被讀成「不賺不賠」。
    assert "return_rate" not in cell
    assert "held_market_value_twd" not in cell


def test_已售出依售出日新到舊排序(client):
    # Act
    sold = _wall(client)["sold"]

    # Assert
    dates = [cell["sold_date"] for cell in sold]
    assert dates == sorted(dates, reverse=True)
    assert _identity(sold[0]) == PIKACHU_25TH[:3]


def test_同一卡種分批賣出時以最近一次售出日排序(client):
    # Act
    cell = _cell(_wall(client)["sold"], MEW)

    # Assert：這一格在牆上的位置由最近一次售出決定
    assert cell["sold_date"] == "2026-06-08"


# --- 持有中的數字 -------------------------------------------------------


def test_持有多張時漲跌幅以總成本對總市值計算(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    cell = _cell(_wall(client)["held"], LUCARIO)

    # Assert：代表你在這個卡種上的實際處境
    total_cost = sum(LUCARIO_COSTS)
    total_value = 3 * LUCARIO_VALUE
    assert cell["held_cost_twd"] == total_cost
    assert cell["held_market_value_twd"] == total_value
    assert cell["return_rate"] == pytest.approx((total_value - total_cost) / total_cost)


def test_漲跌幅不是各張報酬率的平均(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    cell = _cell(_wall(client)["held"], LUCARIO)

    # Assert：兩者在成本不同時必然不相等，平均會讓便宜的那張說話特別大聲
    average = sum((LUCARIO_VALUE - cost) / cost for cost in LUCARIO_COSTS) / 3
    assert cell["return_rate"] != pytest.approx(average)


def test_持有中的每一格列出每一張的個別成本(client):
    # Act
    cell = _cell(_wall(client)["held"], MEW)

    # Assert：展開後看得到逐張成本，不是只有一個總數
    costs = [holding["cost_twd"] for holding in cell["holdings"]]
    assert sorted(costs) == sorted(MEW_HELD_COSTS)


def test_持有中的市值附帶樣本筆數與涵蓋期間(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    value = _cell(_wall(client)["held"], LUCARIO)["market_value"]

    # Assert：使用者必須看得出這個中位數實際代表多長的時間（ADR-0015）
    assert value["sample_count"] > 0
    assert value["sample_from"] <= value["sample_to"]


def test_近30天無成交時帶過期天數(client_factory, confirm_card, crawl):
    # Arrange
    with client_factory() as client:
        _crawled(client, confirm_card, crawl)

    # Act
    with client_factory(now=DEFAULT_NOW + timedelta(days=40)) as later:
        value = _cell(_wall(later)["held"], LUCARIO)["market_value"]

    # Assert：「市場很安靜」與「系統沒更新」要分得開
    assert value["stale_days"] == 41


# --- 已售出的數字 -------------------------------------------------------


def test_已售出直接帶成本與淨賺與報酬率(client):
    # Act
    cell = _cell(_wall(client)["sold"], PIKACHU_25TH)

    # Assert：這些數字是終局的，不需要展開也不會再變
    assert cell["sold_cost_twd"] == PIKACHU_25TH_COST
    assert cell["realized_pnl_twd"] == PIKACHU_25TH_REALIZED
    assert cell["return_rate"] == pytest.approx(
        PIKACHU_25TH_REALIZED / PIKACHU_25TH_COST
    )


def test_已售出的卡種不因為有了市值就冒出未實現損益(client, confirm_card, crawl):
    # Arrange：這個卡種兩張都已售出，且它有市值
    _crawled(client, confirm_card, crawl)

    # Act
    cell = _cell(_wall(client)["sold"], PIKACHU_25TH)

    # Assert
    assert "market_value" not in cell
    assert "unrealized_pnl_twd" not in cell


# --- 首頁畫面 -----------------------------------------------------------


def test_首頁卡圖牆預設分頁是持有中(client):
    # Act
    html = client.get("/").text

    # Assert
    assert "持有中" in html
    assert "已售出" in html
    assert 'id="wall-tab-held" checked' in html


def test_卡圖取自既有的卡圖端點(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert
    assert f"/api/cards/{OLD_TRADES[3]}/image" in html


def test_首頁的每一格顯示卡名與漲跌幅(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert
    total_cost = sum(LUCARIO_COSTS)
    rate = (3 * LUCARIO_VALUE - total_cost) / total_cost
    assert "MEGA Lucario" in html
    assert f"{rate:+.1%}" in html


def test_抽屜看得到逐張成本與市值(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act：抽屜內容由每格的 <template> server-render，仍在 HTML 原始碼裡
    html = client.get("/").text

    # Assert
    for cost in LUCARIO_COSTS:
        assert f"{cost:,}" in html
    assert f"{LUCARIO_VALUE:,}" in html


def test_首頁市值旁並列樣本筆數與涵蓋期間(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text
    value = _cell(_wall(client)["held"], LUCARIO)["market_value"]

    # Assert
    assert f"{value['sample_count']} 筆" in html
    assert f"{value['sample_from']}～{value['sample_to']}" in html


def test_首頁在近30天無成交時顯示過期天數(client_factory, confirm_card, crawl):
    # Arrange
    with client_factory() as client:
        _crawled(client, confirm_card, crawl)

    # Act
    with client_factory(now=DEFAULT_NOW + timedelta(days=40)) as later:
        html = later.get("/").text

    # Assert
    assert "已過期 41 天" in html


def test_首頁的已售出收合格不再放終局數字只留已實現報酬率(client):
    """意圖被 spec §7.8 蓄意反轉：收合狀態只留身分與已實現報酬率，購入成本、售出日、
    已實現損益這三個終局數字改由 §8.4 的抽屜（#33）承接。

    斷言跟著翻面而不是刪除——留住「有人不小心把終局數字加回格子」的護欄，只是方向
    對調。`.fact` 是那三個數字在收合格上的唯一載體，整個類別退役即代表格子清乾淨了。
    #33 會在已售出抽屜補上對應的正面斷言（總成本、總售出、已實現損益、已實現報酬率）。
    """
    # Act
    html = client.get("/").text

    # Assert：終局數字不再直接放在格子上
    assert 'class="fact"' not in html
    # 已實現報酬率仍留在收合狀態（§7.8 的 Collapsed state 保留 realized return rate）
    assert f"{PIKACHU_25TH_REALIZED / PIKACHU_25TH_COST:+.1%}" in html


def test_首頁沒有市值的卡種仍然出現在牆上(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert
    assert "Mew" in html


def test_卡圖牆的百分比不使用倍數(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：全站唯一的報酬率定義是 (結果 − 成本) ÷ 成本
    assert "倍" not in html


def test_已售出的格子一張也標明已售出(client):
    """移除三個 `.fact` 之後售出日不再兜底，`已售出 N 張` 成為格子上唯一能分辨
    持有中／已售出的線索。spec §7.8 的 sold count in metadata **沒有** where
    applicable——對照 §7.7 held 的 holding count where applicable 是刻意的差別，
    已售出那半無條件顯示，只售出一張也要寫「已售出 1 張」。
    """
    # Act：#wall-sold 之後才是已售出那半的 markup
    sold = client.get("/").text.split('id="wall-sold"', 1)[1]

    # Assert
    assert "已售出 1 張" in sold
    assert "已售出 2 張" in sold


def test_算不出報酬率的卡種在格子上顯示破折號(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：spec §7.7——0.0% 會被讀成「不賺不賠」，缺報酬率就給 `—`。
    # （「尚無市值」這句在抽屜的市場區是正確的說法，只是不該出現在收合格的報酬率位。）
    assert '<span class="rate unvalued">—</span>' in html
    assert '<span class="rate unvalued">0.0%' not in html


def test_卡圖用實體卡比例且不裁切(client):
    # Act
    css = client.get("/static/portfolio.css").text
    normalized = css.replace(" ", "")

    # Assert：spec §7.6——實體卡 63mm×88mm，contain 保留完整卡緣，不再用過期的 10/7
    assert "aspect-ratio:63/88" in normalized
    assert "object-fit:contain" in normalized
    assert "10/7" not in normalized


def test_卡圖牆桌機自動填滿手機兩欄(client):
    # Act
    css = client.get("/static/portfolio.css").text
    normalized = css.replace(" ", "").replace("\n", "")

    # Assert：spec §7.5／§11.3——桌機欄數 auto-fill 隨寬度自己長，手機固定兩欄
    assert "repeat(auto-fill,minmax(" in normalized
    assert "max-width:767px" in normalized
    assert "grid-template-columns:repeat(2,1fr)" in normalized


def test_卡圖牆不靠橫向捲動排版(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text
    css = client.get("/static/portfolio.css")

    # Assert
    # 意圖一：卡圖牆不用表格排版——這一條仍鎖在 markup 上。
    assert "<table" not in html
    # ADR-0023 之後，版面樣式從 inline <style> 移進了 static/portfolio.css。以下兩條
    # 的意圖沒變，只是改成對樣式表驗證，並且走同一個 TestClient 接縫——順帶確認
    # /static 掛載沒壞（掛錯的話三頁會裸奔，<link> 回 404）。
    assert css.status_code == 200
    # 意圖二：格子自動換行、頁面不橫捲——欄數用 auto-fill 隨寬度自己長，不靠捲動。
    assert "repeat(auto-fill" in css.text
    # 意圖三：頁面本身永不橫向捲動——收藏總覽這一頁不出現任何 overflow-x。
    assert "overflow-x" not in css.text


# --- 抽屜卡圖的傾斜與反光（ADR-0024）-------------------------------------------
# 斷言比對實際標籤結構，而不是 `"tilt" in html`：頁尾 <script> 與樣板註解裡都會出現
# 這些字，寬鬆比對會恆真。


def _drawer_templates(html: str) -> list[str]:
    return re.findall(r'<template class="cell__detail">(.*?)</template>', html, re.S)


def test_有卡圖的抽屜內容把卡圖包進傾斜容器(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：每個有卡圖的明細，卡圖都緊貼在 .tilt__card 之內，後面接反光層
    with_art = [t for t in _drawer_templates(html) if 'class="drawer__art"' in t]
    assert with_art
    for template in with_art:
        assert re.search(
            r'<div class="tilt">\s*<div class="tilt__card">\s*'
            r'<img class="drawer__art" src="/api/cards/\d+/image" alt="">\s*'
            r'<div class="tilt__glare"></div>\s*</div>\s*</div>',
            template,
        )


def test_沒有卡圖的佔位不被包進傾斜容器(client):
    # Act：沒有確認任何對應，每一格都沒有 apparel id
    html = client.get("/").text

    # Assert
    templates = _drawer_templates(html)
    assert templates
    for template in templates:
        assert '<div class="drawer__art drawer__art--empty"></div>' in template
        assert 'class="tilt' not in template


def test_頁面沒有載入任何外部腳本或樣式表(client, confirm_card, crawl):
    # Arrange
    _crawled(client, confirm_card, crawl)

    # Act
    html = client.get("/").text

    # Assert：<script src> 與 <link href> 都只能是站內路徑
    sources = re.findall(r'<script[^>]*\ssrc="([^"]*)"', html)
    sources += re.findall(r'<link[^>]*\shref="([^"]*)"', html)
    assert sources
    for source in sources:
        assert source.startswith("/"), source
        assert not source.startswith("//"), source


def test_傾斜樣式只作用在抽屜且尊重減少動態偏好(client):
    # Act
    css = client.get("/static/portfolio.css").text

    # Assert
    assert ".tilt__card" in css
    reduced = re.search(
        r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\}\s*\}", css, re.S
    )
    assert reduced and ".tilt__card" in reduced.group(1)
    assert ".tilt__glare" in reduced.group(1)
