"""首頁的持有品增刪改入口（承接 #10 的操作，只換位置）。

操作靠近它們要動的那筆資料：售出、編輯、刪除在**卡片的展開區**裡，一格一個卡種，
展開後逐張列出。新增持有品在**頁面層級的工具列**，不再每列一份——重複的按鈕會把
畫面塞滿，而「新增」本來就不屬於任何一張既有的持有品。

既有的持有品 API 完全沒動，本檔只驗證入口的位置與資料是否到得了前端；API 本身的
行為由 test_holdings_crud.py 守著。
"""

from conftest import LUCARIO, PRINTING_ERROR

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


# --- 售出、編輯、刪除在展開區 -------------------------------------------


def test_持有中的每一格展開後有售出編輯與刪除(client):
    # Act
    page = _page(client)

    # Assert：操作就在那一筆旁邊，因此不必先在別的地方查出 id
    assert 'onclick="openSale(this)"' in page
    assert 'onclick="openEdit(this)"' in page
    assert 'onclick="openDelete(this)"' in page


def test_已售出的每一格是改回持有中而不是售出(client):
    # Act
    page = _page(client)

    # Assert：已經賣掉的那張沒有「再賣一次」這種操作
    assert 'onclick="openUnsell(this)"' in page


def test_五個增刪改操作在首頁全部到齊(client):
    # Act
    page = _page(client)

    # Assert：新增、售出、編輯、改回持有中、刪除
    for entry in ("openCreate", "openSale", "openEdit", "openUnsell", "openDelete"):
        assert f"{entry}(" in page


def test_操作入口不再散在唯讀表格的每一列(client):
    # Act
    page = _page(client)

    # Assert：卡圖牆不用表格排版，操作也就不再是「表格的一欄」
    assert "<table" not in page


# --- 動到哪一筆說得出來 -------------------------------------------------


def test_刪除前的確認需要的那一筆資料就在畫面上(client):
    # Arrange
    _add_holding(client, LUCARIO, cost_twd=2600, purchase_date="2026-03-15")

    # Act
    page = _page(client)

    # Assert：確認訊息要說得出是**具體哪一筆**，避免手滑刪掉買入紀錄
    assert 'data-purchase="2026-03-15"' in page
    assert 'data-cost="2600"' in page
    assert 'data-kind="MEGA Lucario（M2a #228）"' in page


def test_已售出的那一筆帶著已實現損益供確認訊息使用(client):
    # Arrange
    holding_id = _add_holding(client, LUCARIO, cost_twd=2600)
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    # Act
    page = _page(client)

    # Assert：刪掉一筆已售出的會動到已實現損益，確認時必須說得出會少多少
    assert 'data-realized="1400"' in page


def test_每一張持有品各自帶著自己的入口(client):
    # Arrange：同一個卡種買了兩張，成本不同
    first = _add_holding(client, PRINTING_ERROR, cost_twd=2600)
    second = _add_holding(client, PRINTING_ERROR, cost_twd=3100)

    # Act
    page = _page(client)

    # Assert：一格是一個卡種，但賣掉的是其中**某一張**（ADR-0009），系統不自動挑
    assert f'data-id="{first}"' in page
    assert f'data-id="{second}"' in page


# --- 完成與失敗 ---------------------------------------------------------


def test_首頁載得到操作用的對話框(client):
    # Act
    page = _page(client)

    # Assert：刪除前有明確確認，靠的就是這個對話框
    assert 'id="editor"' in page
    assert "確定刪除" in page


def test_操作完成後畫面自動反映新狀態(client):
    # Act
    page = _page(client)

    # Assert：衍生數字都是算出來的，重畫一次就全部正確，不必手動重新整理
    assert "location.reload()" in page


def test_操作失敗時說得出具體原因(client):
    # Act
    page = _page(client)

    # Assert：只說一句「失敗」等於沒說
    assert "detailOf" in page
