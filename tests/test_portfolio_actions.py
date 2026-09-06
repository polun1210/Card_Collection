"""首頁的增刪改入口與卡片明細抽屜的唯讀性。

#33 之後首頁明細**唯讀**（spec §8.3／§8.4）：點卡圖開一個抽屜，裡面只讀不寫。
售出、編輯、刪除、改回持有中屬於持有品頁（#34），首頁的卡圖牆不再有這些逐筆入口。
唯一留在首頁的增刪改動作是頁首的 `＋ 新增持有品`（`openCreate`，住在
`_holding_editor.html`）——它不屬於任何一張既有持有品，所以不在移除之列。

抽屜內容由每格一個隱藏 `<template class="cell__detail">` server-render，點擊時
clone 進抽屜。內容仍在 HTML 原始碼裡，所以字串斷言驗得到（見 `_portfolio_wall.html`）。

既有的持有品 API 完全沒動；API 本身的行為由 test_holdings_crud.py 守著。
"""

from conftest import LUCARIO, PRINTING_ERROR


def _drawer_of(html: str, card: tuple, scope: str = "held") -> str:
    """某個卡種在 `wall-{scope}` 那一格的 `<template class="cell__detail">` 內容。

    卡種身分含卡名（ADR-0008）：系列＋卡號不唯一（錯體版與正常版同系列同號），
    同名也可能有多個卡種（同一隻寶可夢出現在多個系列）。所以要同時比對
    `data-code`（系列 #卡號）與 `data-name`（卡名）。
    """
    series, number, name = card[:3]
    region = html[html.index(f'id="wall-{scope}"') : html.index('id="card-drawer"')]
    if scope == "held":
        region = region[: region.index('id="wall-sold"')]
    for chunk in region.split('<div class="cell tile">')[1:]:
        if f'data-name="{name}"' in chunk and f'data-code="{series} #{number}"' in chunk:
            opened = chunk.index('<template class="cell__detail">')
            return chunk[opened : chunk.index("</template>", opened)]
    raise AssertionError(f"wall-{scope} 裡找不到 {name}（{series} #{number}）的格子")

NEW_KIND = {
    "series_raw": "M2b",
    "number_raw": "12",
    "card_name_raw": "Rayquaza ex",
}


def _page(client) -> str:
    return client.get("/").text


def _kind_id(client, card: tuple) -> int:
    row = next(
        row
        for row in client.get("/api/mapping/queue").json()
        if (row["series_raw"], row["number_raw"], row["card_name_raw"]) == card[:3]
    )
    return row["id"]


def _add_holding(client, card: tuple, cost_twd=2600, purchase_date="2026-03-15") -> int:
    response = client.post(
        "/api/holdings",
        json={
            "mapping_candidate_id": _kind_id(client, card),
            "cost_twd": cost_twd,
            "purchase_date": purchase_date,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


# --- 新增在頁面層級 -----------------------------------------------------


def test_新增持有品的入口在頁面層級的工具列(client):
    # Act
    page = _page(client)

    # Assert：不必先找到一張卡才記得了一筆購入
    assert 'onclick="openCreate()"' in page


def test_新增持有品的入口不再每一格一份(client):
    # Act
    page = _page(client)

    # Assert：68 個卡種不該長出 68 顆一模一樣的按鈕
    assert page.count('onclick="openCreate()"') == 1


def test_新增持有品挑得到尚未確認的卡種(client):
    # Arrange
    client.post("/api/card-kinds", json=NEW_KIND)

    # Act
    page = _page(client)

    # Assert：記一筆購入不該被「行情對應還沒做完」擋住
    assert "Rayquaza ex（M2b #12）" in page


# --- 首頁的明細唯讀 ---------------------------------------------------


def test_首頁的卡圖牆沒有逐張售出編輯刪除入口(client):
    # Act
    page = _page(client)

    # Assert：這四個逐筆入口不再出現在首頁（它們屬於持有品頁 #34）
    for entry in ("openSale", "openEdit", "openDelete", "openUnsell"):
        assert f'onclick="{entry}(' not in page
    # 陪站崗的 in：卡圖牆確實渲染了（否則「沒有入口」是空的真），且唯一該留的
    # 主動作——頁首的 ＋ 新增持有品——還在
    assert 'id="wall-held"' in page
    assert 'id="wall-sold"' in page
    assert 'onclick="openCreate()"' in page


def test_已售出的明細也不提供改回持有中(client):
    # Act
    drawer = _drawer_of(_page(client), ("S12a", "183", "Mew"), scope="sold")

    # Assert：已售出明細講的是收藏史，不是可改的狀態
    assert "onclick=" not in drawer
    assert "openUnsell" not in drawer
    # 陪站崗：抽屜確實有內容——售出紀錄那一段在
    assert "售出紀錄" in drawer


def test_首頁唯一的增刪改入口是頁首的新增持有品(client):
    # Act
    page = _page(client)

    # Assert：openCreate 恰好一次（頁首），其餘四個逐筆動作一次都沒有
    assert page.count('onclick="openCreate()"') == 1
    for entry in ("openSale", "openEdit", "openDelete", "openUnsell"):
        assert f'onclick="{entry}' not in page


def test_卡圖牆不用表格排版(client):
    # Act
    page = _page(client)

    # Assert：卡圖牆用 grid 換行、不用 <table>（interface.md §5 第 10 條）
    assert "<table" not in page
    assert 'id="wall-held"' in page  # 陪站崗：牆確實渲染了


# --- 抽屜唯讀，但看得到哪一筆是哪一筆 ---------------------------------


def test_持有中抽屜以唯讀方式顯示逐張購入日與成本(client):
    # Arrange
    _add_holding(client, LUCARIO, cost_twd=2600, purchase_date="2026-03-15")

    # Act
    drawer = _drawer_of(_page(client), LUCARIO)

    # Assert：那一筆的購入日與成本看得到（spec §8.3「我的持有明細」唯讀）
    assert "2026-03-15" in drawer
    assert "2,600" in drawer
    # 陪站崗的 not-in：確實唯讀——沒有 onclick、沒有掛給對話框的 data 屬性
    assert "onclick=" not in drawer
    assert "data-cost=" not in drawer


def test_已售出抽屜逐筆顯示購入到售出的生命週期(client):
    # Arrange
    holding_id = _add_holding(client, LUCARIO, cost_twd=2600, purchase_date="2026-03-15")
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    # Act：LUCARIO 現在有一筆已售出，落在 wall-sold
    drawer = _drawer_of(_page(client), LUCARIO, scope="sold")

    # Assert：購入資訊 → 售出資訊 的完整生命週期，逐筆帶已實現損益（4000 − 2600）
    assert "2026-03-15" in drawer
    assert "4,000" in drawer
    assert "+1,400" in drawer


def test_持有中抽屜逐張列出同卡種的每一筆(client):
    # Arrange：同一個卡種買了兩張，成本不同
    _add_holding(client, PRINTING_ERROR, cost_twd=2600)
    _add_holding(client, PRINTING_ERROR, cost_twd=3100)

    # Act
    drawer = _drawer_of(_page(client), PRINTING_ERROR)

    # Assert：兩筆各自看得到（ADR-0009：賣哪一張由人在持有品頁指定，這裡先確保
    # 逐張可見，不被聚合成一個總數）
    assert "2,600" in drawer
    assert "3,100" in drawer


# --- 頁首新增持有品的對話框 -------------------------------------------


def test_首頁載得到新增持有品的對話框(client):
    # Act
    page = _page(client)

    # Assert：頁首的 ＋ 新增持有品（openCreate）用的就是這個對話框
    assert 'id="editor"' in page
    assert 'onclick="openCreate()"' in page
    # 對話框開得起來還不夠——卡種下拉要有東西可選。all_kinds 現在是首頁 context
    # 裡唯一只服務於頁首那顆按鈕的欄位，#33 移除牆上全部增刪改之後，它看起來會很像
    # 可以順手清掉的殘留。清掉的話這頁就再也記不了新的一筆。
    assert 'id="kind-options"' in page
    assert "MEGA Lucario（M2a #228）" in page  # 下拉裡真的有卡種可選


def test_新增完成後畫面自動反映新狀態(client):
    # Act
    page = _page(client)

    # Assert：衍生數字都是算出來的，重畫一次就全部正確，不必手動重新整理
    assert "location.reload()" in page


def test_操作失敗時說得出具體原因(client):
    # Act
    page = _page(client)

    # Assert：只說一句「失敗」等於沒說
    assert "detailOf" in page
