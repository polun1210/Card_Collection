"""持有品 CRUD 與售出流程的外部行為。

斷言一律走 HTTP，不讀資料庫、不呼叫 repository。這樣內部怎麼重構測試都不會紅；
而測試紅的時候，紅的一定是使用者看得到的行為變了。

這一組守的是同一件事：**這本帳必須跟得上現實，而且不准安靜地算錯。**
"""

import pytest

from conftest import DEFAULT_NOW, LUCARIO, PIKACHU_25TH

TODAY = DEFAULT_NOW.date().isoformat()
TOMORROW = "2026-08-27"


def _holdings(client) -> list[dict]:
    response = client.get("/api/holdings")
    assert response.status_code == 200, response.text
    return response.json()


def _summary(client) -> dict:
    response = client.get("/api/holdings/summary")
    assert response.status_code == 200, response.text
    return response.json()


def _find(client, holding_id: int) -> dict | None:
    return next(
        (row for row in _holdings(client) if row["id"] == holding_id),
        None,
    )


def _kind_id(client, card: tuple) -> int:
    """卡種列 id。持有品掛在卡種列上（ADR-0012），新增時要指定它。"""
    series, number, card_name = card[:3]
    row = next(
        row
        for row in client.get("/api/mapping/queue").json()
        if (row["series_raw"], row["number_raw"], row["card_name_raw"])
        == (series, number, card_name)
    )
    return row["id"]


@pytest.fixture
def add_holding(client):
    """新增一筆持有品，回傳它的 id。"""

    def add(mapping_candidate_id: int, **fields) -> int:
        response = client.post(
            "/api/holdings",
            json={"mapping_candidate_id": mapping_candidate_id, "cost_twd": 2600}
            | fields,
        )
        assert response.status_code == 200, response.text
        return response.json()["id"]

    return add


# --- 新增持有品 ---------------------------------------------------------


def test_新增的持有品立刻出現在清單裡(client, add_holding):
    kind = _kind_id(client, LUCARIO)

    holding_id = add_holding(kind, cost_twd=2600)

    added = _find(client, holding_id)
    assert added is not None
    assert added["card_name_raw"] == "MEGA Lucario"
    assert added["cost_twd"] == 2600
    assert added["status"] == "held"


def test_新增時購入日預設今天(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))

    # 絕大多數情況是當天記帳，不該每次都要輸入日期。
    assert _find(client, holding_id)["purchase_date"] == TODAY


def test_新增時可以指定購入日(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), purchase_date="2026-03-15")

    # 預設今天，但補登昨天的交易也必須做得到（ADR-0009）。
    assert _find(client, holding_id)["purchase_date"] == "2026-03-15"


def test_同一個卡種可以新增多筆完全相同的持有品(client, add_holding):
    kind = _kind_id(client, LUCARIO)

    first = add_holding(kind, cost_twd=2600, purchase_date="2026-03-15")
    second = add_holding(kind, cost_twd=2600, purchase_date="2026-03-15")

    # 欄位完全相同的兩筆是兩張實體卡，不是重複資料。任何去重都會吃掉真實資產。
    assert first != second
    assert _find(client, first) is not None
    assert _find(client, second) is not None


def test_新增後持有成本總和跟著增加(client, add_holding):
    before = _summary(client)

    add_holding(_kind_id(client, LUCARIO), cost_twd=2600)

    after = _summary(client)
    assert after["held_count"] == before["held_count"] + 1
    assert after["held_cost_twd"] == before["held_cost_twd"] + 2600


def test_購入成本不是正整數時被擋下(client):
    kind = _kind_id(client, LUCARIO)

    response = client.post(
        "/api/holdings", json={"mapping_candidate_id": kind, "cost_twd": 0}
    )

    assert response.status_code == 400
    assert "購入成本" in response.json()["detail"]


def test_購入日在未來時被擋下(client):
    kind = _kind_id(client, LUCARIO)

    response = client.post(
        "/api/holdings",
        json={"mapping_candidate_id": kind, "cost_twd": 2600, "purchase_date": TOMORROW},
    )

    # 未來的日期多半是打錯年份，當場擋下比事後查帳容易得多。
    assert response.status_code == 400
    assert "未來" in response.json()["detail"]


def test_購入日寫法無法解析時被擋下(client):
    kind = _kind_id(client, LUCARIO)

    response = client.post(
        "/api/holdings",
        json={
            "mapping_candidate_id": kind,
            "cost_twd": 2600,
            "purchase_date": "去年三月",
        },
    )

    assert response.status_code == 400
    assert "去年三月" in response.json()["detail"]


def test_掛到不存在的卡種上時回404(client):
    response = client.post(
        "/api/holdings", json={"mapping_candidate_id": 999999, "cost_twd": 2600}
    )

    assert response.status_code == 404


def test_手動記的持有品沒有來源列號(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))

    # 匯入來的有列號、手動記的沒有——日後對帳查得到源頭。
    assert _find(client, holding_id)["source_row_number"] is None


def test_新增的持有品鑑定欄位預設為PSA10(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))

    assert _find(client, holding_id)["grading_raw"] == "PSA 10"


# --- 售出 ---------------------------------------------------------------


def test_售出後從未實現損益移到已實現損益(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), cost_twd=2600)
    before = _summary(client)

    response = client.post(
        f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000}
    )
    assert response.status_code == 200, response.text

    after = _summary(client)
    assert after["held_count"] == before["held_count"] - 1
    assert after["sold_count"] == before["sold_count"] + 1
    assert after["realized_pnl_twd"] == before["realized_pnl_twd"] + 1400
    assert after["held_cost_twd"] == before["held_cost_twd"] - 2600


def test_售出日預設今天(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), purchase_date="2026-03-15")

    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    assert _find(client, holding_id)["sold_date"] == TODAY


def test_售出日可以指定(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), purchase_date="2026-03-15")

    client.post(
        f"/api/holdings/{holding_id}/sale",
        json={"sold_price_twd": 4000, "sold_date": "2026-05-06"},
    )

    assert _find(client, holding_id)["sold_date"] == "2026-05-06"


def test_售出價未填時被擋下(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))

    response = client.post(f"/api/holdings/{holding_id}/sale", json={})

    # 少了售出價就是一筆算不出已實現損益的已售出持有品。
    assert response.status_code in (400, 422)
    assert _find(client, holding_id)["status"] == "held"


def test_售出價不是正整數時被擋下(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))

    response = client.post(
        f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 0}
    )

    assert response.status_code == 400
    assert "售出價" in response.json()["detail"]


def test_售出日早於購入日時被擋下(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), purchase_date="2026-03-15")

    response = client.post(
        f"/api/holdings/{holding_id}/sale",
        json={"sold_price_twd": 4000, "sold_date": "2026-01-01"},
    )

    # 賣在買之前是時間顛倒。這條規則匯入時已經在把關，CRUD 不能比它鬆。
    assert response.status_code == 400
    assert "早於" in response.json()["detail"]
    assert _find(client, holding_id)["status"] == "held"


def test_已售出的持有品不能再售出一次(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    again = client.post(
        f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 9999}
    )

    # 覆蓋掉原本的售出紀錄等於安靜地改寫已實現損益。
    assert again.status_code == 409
    assert _find(client, holding_id)["sold_price_twd"] == 4000


def test_售出的是我指定的那一張(client, add_holding):
    kind = _kind_id(client, LUCARIO)
    cheap = add_holding(kind, cost_twd=2600, purchase_date="2026-03-15")
    pricey = add_holding(kind, cost_twd=3300, purchase_date="2026-04-20")

    client.post(f"/api/holdings/{pricey}/sale", json={"sold_price_twd": 4000})

    # 不自動 FIFO、不自動挑成本最高者（ADR-0009）：系統挑的話，已實現損益會變成
    # 「會計上的真」而非事實上的真，而且事後無從得知系統挑了哪一張。
    assert _find(client, pricey)["status"] == "sold"
    assert _find(client, cheap)["status"] == "held"


def test_售出後那筆不再接上市值(client, add_holding, confirm_card, crawl):
    # 確認後那一列就離開待確認清單，卡種列 id 由 confirm_card 回傳。
    kind = confirm_card(client, LUCARIO)
    crawl(client)
    holding_id = add_holding(kind, cost_twd=2600)
    assert "market_value_twd" in _find(client, holding_id), "這個測試要有市值才有意義"

    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    sold = _find(client, holding_id)
    # 已售出的持有品有終局的售出價，不會因為這個卡種現在有市值就冒出未實現損益。
    assert "unrealized_pnl_twd" not in sold
    assert "market_value_twd" not in sold


# --- 編輯 ---------------------------------------------------------------


def test_修改購入成本後未實現損益跟著變(client, add_holding, confirm_card, crawl):
    kind = confirm_card(client, LUCARIO)
    crawl(client)
    holding_id = add_holding(kind, cost_twd=2600)
    before = _find(client, holding_id)["unrealized_pnl_twd"]

    response = client.patch(f"/api/holdings/{holding_id}", json={"cost_twd": 2000})
    assert response.status_code == 200, response.text

    # 衍生數字是算出來的，不是存下來的——改完就對，不需要任何重算機制。
    assert _find(client, holding_id)["unrealized_pnl_twd"] == before + 600


def test_修改持有品掛的卡種(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))
    pikachu = _kind_id(client, PIKACHU_25TH)

    response = client.patch(
        f"/api/holdings/{holding_id}", json={"mapping_candidate_id": pikachu}
    )
    assert response.status_code == 200, response.text

    # 當初認錯卡要修得好，且不必刪掉重建而失去購入紀錄。
    assert _find(client, holding_id)["card_name_raw"] == "Pikachu 25th"


def test_修改已售出持有品的售出價後已實現損益跟著變(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), cost_twd=2600)
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})
    before = _summary(client)["realized_pnl_twd"]

    client.patch(f"/api/holdings/{holding_id}", json={"sold_price_twd": 5000})

    assert _summary(client)["realized_pnl_twd"] == before + 1000


def test_把誤標的售出改回持有中(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    response = client.patch(
        f"/api/holdings/{holding_id}",
        json={"sold_date": None, "sold_price_twd": None},
    )
    assert response.status_code == 200, response.text

    # 按錯一下不必刪掉整筆重建。
    assert _find(client, holding_id)["status"] == "held"


def test_改回持有中時售出價一併清空(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    client.patch(
        f"/api/holdings/{holding_id}",
        json={"sold_date": None, "sold_price_twd": None},
    )

    # 狀態判定只看售出日，殘留的售出價會變成一個永遠沒有人看得見的數字。
    assert _find(client, holding_id)["sold_price_twd"] is None


def test_只清掉售出日而留著售出價會被擋下(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    response = client.patch(f"/api/holdings/{holding_id}", json={"sold_date": None})

    assert response.status_code == 400
    assert _find(client, holding_id)["status"] == "sold"


def test_編輯不能繞過成本必須為正的規則(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), cost_twd=2600)

    response = client.patch(f"/api/holdings/{holding_id}", json={"cost_twd": -100})

    assert response.status_code == 400
    assert _find(client, holding_id)["cost_twd"] == 2600


def test_編輯不存在的持有品回404(client):
    response = client.patch("/api/holdings/999999", json={"cost_twd": 2600})

    assert response.status_code == 404


# --- 刪除 ---------------------------------------------------------------


def test_刪除後持有品從清單消失(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))

    response = client.delete(f"/api/holdings/{holding_id}")
    assert response.status_code == 200, response.text

    assert _find(client, holding_id) is None


def test_刪除持有中的持有品後持有成本減少(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), cost_twd=2600)
    before = _summary(client)

    client.delete(f"/api/holdings/{holding_id}")

    after = _summary(client)
    assert after["held_count"] == before["held_count"] - 1
    assert after["held_cost_twd"] == before["held_cost_twd"] - 2600


def test_刪除已售出的持有品後已實現損益減少(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), cost_twd=2600)
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})
    before = _summary(client)

    client.delete(f"/api/holdings/{holding_id}")

    after = _summary(client)
    assert after["sold_count"] == before["sold_count"] - 1
    assert after["realized_pnl_twd"] == before["realized_pnl_twd"] - 1400


def test_刪除不存在的持有品回404(client):
    assert client.delete("/api/holdings/999999").status_code == 404


# --- 新增卡種 -----------------------------------------------------------

NEW_KIND = {"series_raw": "M2b", "number_raw": "12", "card_name_raw": "Rayquaza ex"}


def test_新增卡種後可以掛持有品上去(client):
    created = client.post("/api/card-kinds", json=NEW_KIND)
    assert created.status_code == 200, created.text

    response = client.post(
        "/api/holdings",
        json={"mapping_candidate_id": created.json()["id"], "cost_twd": 5000},
    )

    # 買到不在那 68 個裡的新卡是最常見的情境，沒有卡種列就無處可掛（ADR-0012）。
    assert response.status_code == 200, response.text
    assert response.json()["card_name_raw"] == "Rayquaza ex"


def test_新增的卡種進入待確認清單(client):
    client.post("/api/card-kinds", json=NEW_KIND)

    queue = client.get("/api/mapping/queue").json()
    # 沿用既有的搜尋 → 確認 → 抓卡圖流程，不必學一套新的操作。
    assert any(row["card_name_raw"] == "Rayquaza ex" for row in queue)


def test_新增重複的卡種時回409並指出既有的那一列(client):
    first = client.post("/api/card-kinds", json=NEW_KIND)

    again = client.post("/api/card-kinds", json=NEW_KIND)

    # 兩個代表同一張卡的卡種列會讓持有品分裂到兩邊，市值也跟著分裂。
    assert again.status_code == 409
    assert again.json()["detail"]["id"] == first.json()["id"]


def test_新增卡種時系列代碼不做收斂(client):
    client.post("/api/card-kinds", json=NEW_KIND | {"series_raw": "SVP"})

    response = client.post("/api/card-kinds", json=NEW_KIND | {"series_raw": "SV-P"})

    # SVP（英文版）與 SV-P（日文版）是不同的系列，不是同一個系列的兩種寫法（ADR-0011）。
    assert response.status_code == 200, response.text


def test_掛在未確認卡種上的持有品不長出市值與未實現損益(client, add_holding):
    created = client.post("/api/card-kinds", json=NEW_KIND).json()

    holding_id = add_holding(created["id"], cost_twd=5000)

    holding = _find(client, holding_id)
    # 缺市值就讓欄位不存在，不是 null 也不是 0——0 會被讀成「不賺不賠」。
    assert "market_value_twd" not in holding
    assert "unrealized_pnl_twd" not in holding
    assert holding["apparel_id"] is None


def test_清空購入日會被擋下(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))

    response = client.patch(f"/api/holdings/{holding_id}", json={"purchase_date": None})

    # 售出欄位清得掉，購入欄位清不掉——沒有購入日的持有品算不出任何東西。
    assert response.status_code == 400
    assert "購入日" in response.json()["detail"]
    assert _find(client, holding_id)["purchase_date"] == TODAY


def test_清空購入成本會被擋下(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), cost_twd=2600)

    response = client.patch(f"/api/holdings/{holding_id}", json={"cost_twd": None})

    assert response.status_code == 400
    assert "購入成本" in response.json()["detail"]
    assert _find(client, holding_id)["cost_twd"] == 2600


# --- 畫面 ---------------------------------------------------------------


def _page(client) -> str:
    return client.get("/holdings").text


def test_持有品頁有新增持有品與新增卡種的入口(client):
    page = _page(client)

    # 不必開另一個工具或打 API。
    assert "新增持有品" in page
    assert "新增卡種" in page


def test_每一筆持有中的持有品旁邊都有售出與刪除(client, add_holding):
    add_holding(_kind_id(client, LUCARIO))

    page = _page(client)
    # 操作入口就在那一筆旁邊，因此不必先在別的地方查出 id。
    assert 'onclick="openSale(this)"' in page
    assert 'onclick="openEdit(this)"' in page
    assert 'onclick="openDelete(this)"' in page


def test_已售出的持有品旁邊是改回持有中而不是售出(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO))
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    page = _page(client)
    assert 'onclick="openUnsell(this)"' in page


def test_刪除確認需要的那一筆資料就在畫面上(client, add_holding):
    add_holding(_kind_id(client, LUCARIO), cost_twd=2600, purchase_date="2026-03-15")

    page = _page(client)
    # 確認訊息要說得出是**具體哪一筆**，所以卡種、購入日與成本都必須到得了前端。
    assert 'data-purchase="2026-03-15"' in page
    assert 'data-cost="2600"' in page
    assert 'data-kind="MEGA Lucario（M2a #228）"' in page


def test_已售出的持有品帶著已實現損益供確認訊息使用(client, add_holding):
    holding_id = add_holding(_kind_id(client, LUCARIO), cost_twd=2600)
    client.post(f"/api/holdings/{holding_id}/sale", json={"sold_price_twd": 4000})

    page = _page(client)
    # 刪掉一筆已售出的會動到已實現損益，確認時必須說得出會少多少。
    assert 'data-realized="1400"' in page


def test_新增持有品挑得到尚未確認的卡種(client):
    client.post("/api/card-kinds", json=NEW_KIND)

    page = _page(client)
    # 記一筆購入不該被「行情對應還沒做完」擋住。
    assert "Rayquaza ex（M2b #12）" in page


def test_新增持有品可以在對話框裡當場新建卡種(client):
    page = _page(client)

    # spec §9.7：卡種不在清單裡時，使用者可以當場新建卡種並直接完成這一筆，
    # 不強迫先做完 SNKRDUNK 對應。契約是 openCreate() 的卡種下拉多一個
    # 「＋ 新增卡種…」選項，選了才展開系列／卡號／卡名三個欄位。舊版
    # （8547bfe）的 openCreate 只有 kindSelect(null)，這些標記都不存在。
    assert "＋ 新增卡種…" in page
    assert 'id="new-kind-fields"' in page
    assert 'id="f-new-series"' in page


def test_持有品頁帶著即時篩選的欄位與可篩字串(client):
    page = _page(client)

    # spec §9.2：打字即篩選卡名、系列代碼、卡號，無送出按鈕、無篩選面板。
    # 過濾邏輯是前端腳本、測不到；但契約測得到——篩選欄位存在，且每個卡種
    # 區塊帶著把三個欄位串起來的可篩字串。舊版沒有搜尋欄、沒有 data-search。
    assert 'id="holdings-search"' in page
    assert 'data-search="' in page
    # MEGA Lucario（M2a #228）這一組：卡名、系列代碼、卡號三者都在可篩字串裡。
    assert 'data-search="mega lucario m2a 228"' in page


def test_持有品頁備妥無結果時的提示(client):
    page = _page(client)

    # spec §9.2：找不到時給一句話。這句是預先渲染、由腳本切換顯示，所以在 HTML 裡。
    # 舊版沒有搜尋，也就沒有這句。
    assert "找不到符合項目的持有品" in page


def test_已售出的刪除確認帶出售出日與售出價(client, add_holding):
    holding_id = add_holding(
        _kind_id(client, LUCARIO), cost_twd=2600, purchase_date="2026-03-15"
    )
    client.post(
        f"/api/holdings/{holding_id}/sale",
        json={"sold_price_twd": 4000, "sold_date": "2026-05-06"},
    )

    page = _page(client)
    # spec §9.8：已售出的刪除確認要另外列出售出日、售出價，以及刪掉後會消失多少
    # 已實現損益。確認訊息在腳本裡組出來，斷言那幾個模板片段有服務出去。舊版
    # （8547bfe）的 sold 分支只有「刪除後已實現損益會減少 …」，沒有售出日與售出價。
    assert "${lot.sold} 售出 ${money(lot.price)}" in page
    assert "已實現損益會少掉 ${money(lot.realized)}" in page


def test_手機上仍讀得到持有品頁(client):
    page = _page(client)

    # 手機是唯讀場景，這一刀不能把它弄壞。
    assert 'name="viewport"' in page
    assert 'class="tblwrap"' in page
