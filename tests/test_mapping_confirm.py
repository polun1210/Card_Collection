"""確認、否決與推翻的外部行為。"""

MEGA_LUCARIO = (722241, 834208)
PRINTING_ERROR = (744296, 859607)
CHARIZARD_PROMO = (91103, 167274)


def _find(client, series: str, number: str, card_name: str) -> dict | None:
    rows = client.get("/api/mapping/queue").json()
    for row in rows:
        if (
            row["series_raw"] == series
            and row["number_raw"] == number
            and row["card_name_raw"] == card_name
        ):
            return row
    return None


def _confirm(client, row_id: int, apparel_id: int):
    return client.post(
        "/api/mapping/confirm",
        json={"mapping_candidate_id": row_id, "apparel_id": apparel_id},
    )


def test_確認後卡種主檔存下的是productCatalogId而非apparelId(client):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")
    apparel_id, product_catalog_id = MEGA_LUCARIO

    # Act
    assert _confirm(client, row["id"], apparel_id).status_code == 200

    # Assert
    card = client.get(f"/api/cards/{apparel_id}").json()
    assert card["product_catalog_id"] == product_catalog_id
    assert card["product_catalog_id"] != apparel_id


def test_確認後的卡種帶著卡名卡圖與Notion原始寫法(client):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")

    # Act
    _confirm(client, row["id"], MEGA_LUCARIO[0])

    # Assert
    card = client.get(f"/api/cards/{MEGA_LUCARIO[0]}").json()
    assert "MEGA Lucario ex MA" in card["name_en"]
    assert "メガルカリオ" in card["name_ja"]
    assert card["card_code"] == "M2a 228/193"
    assert card["image_url"].startswith("https://cdn.snkrdunk.com/")
    assert (card["series_raw"], card["number_raw"], card["card_name_raw"]) == (
        "M2a",
        "228",
        "MEGA Lucario",
    )


def test_取不到productCatalogId時確認失敗且主檔沒有半成品(client, snkrdunk):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")
    snkrdunk.strip_product_catalog_id = True

    # Act
    response = _confirm(client, row["id"], MEGA_LUCARIO[0])

    # Assert
    assert response.status_code >= 500
    assert client.get(f"/api/cards/{MEGA_LUCARIO[0]}").status_code == 404
    assert _find(client, "M2a", "228", "MEGA Lucario") is not None
    assert client.get("/api/mapping/progress").json()["confirmed"] == 0


def test_已確認的列不再出現在待確認清單(client):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")

    # Act
    _confirm(client, row["id"], MEGA_LUCARIO[0])

    # Assert
    assert _find(client, "M2a", "228", "MEGA Lucario") is None


def test_否決後該列離開清單也不進主檔(client):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")

    # Act
    response = client.post("/api/mapping/reject", json={"mapping_candidate_id": row["id"]})

    # Assert
    assert response.status_code == 200
    assert _find(client, "M2a", "228", "MEGA Lucario") is None
    assert client.get("/api/mapping/progress").json()["rejected"] == 1
    assert client.get(f"/api/cards/{MEGA_LUCARIO[0]}").status_code == 404


def test_推翻確認後該列回到清單且主檔移除該卡種(client):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")
    _confirm(client, row["id"], MEGA_LUCARIO[0])

    # Act
    response = client.delete(f"/api/mapping/confirm/{row['id']}")

    # Assert
    assert response.status_code == 200
    assert _find(client, "M2a", "228", "MEGA Lucario") is not None
    assert client.get(f"/api/cards/{MEGA_LUCARIO[0]}").status_code == 404
    assert client.get("/api/mapping/progress").json()["confirmed"] == 0


def test_手動輸入不在候選裡的apparelId也能確認(client):
    # Arrange：91103 是 S-P 104 的噴火龍，不在 M2a 228 的候選裡
    row = _find(client, "M2a", "228", "MEGA Lucario")

    # Act
    response = _confirm(client, row["id"], CHARIZARD_PROMO[0])

    # Assert
    assert response.status_code == 200
    assert (
        client.get(f"/api/cards/{CHARIZARD_PROMO[0]}").json()["product_catalog_id"]
        == CHARIZARD_PROMO[1]
    )


def test_錯體版與正常版各自確認到不同的apparelId(client):
    # Arrange
    normal = _find(client, "M2a", "228", "MEGA Lucario")
    error_card = _find(client, "M2a", "228", "MEGA Lucario Printing Error")

    # Act
    _confirm(client, normal["id"], MEGA_LUCARIO[0])
    _confirm(client, error_card["id"], PRINTING_ERROR[0])

    # Assert
    assert client.get(f"/api/cards/{MEGA_LUCARIO[0]}").json()["product_catalog_id"] == MEGA_LUCARIO[1]
    assert client.get(f"/api/cards/{PRINTING_ERROR[0]}").json()["product_catalog_id"] == PRINTING_ERROR[1]
    assert client.get("/api/mapping/progress").json()["confirmed"] == 2


def test_進度隨確認否決推翻正確變動(client):
    # Arrange
    normal = _find(client, "M2a", "228", "MEGA Lucario")
    error_card = _find(client, "M2a", "228", "MEGA Lucario Printing Error")

    # Act / Assert
    assert client.get("/api/mapping/progress").json() == {
        "confirmed": 0, "rejected": 0, "pending": 68
    }
    _confirm(client, normal["id"], MEGA_LUCARIO[0])
    assert client.get("/api/mapping/progress").json() == {
        "confirmed": 1, "rejected": 0, "pending": 67
    }
    client.post("/api/mapping/reject", json={"mapping_candidate_id": error_card["id"]})
    assert client.get("/api/mapping/progress").json() == {
        "confirmed": 1, "rejected": 1, "pending": 66
    }
    client.delete(f"/api/mapping/confirm/{normal['id']}")
    assert client.get("/api/mapping/progress").json() == {
        "confirmed": 0, "rejected": 1, "pending": 67
    }


def test_重啟服務後進度與卡種主檔不變(client_factory):
    # Act
    with client_factory() as client:
        row = _find(client, "M2a", "228", "MEGA Lucario")
        _confirm(client, row["id"], MEGA_LUCARIO[0])

    with client_factory() as client:
        # Assert
        assert client.get("/api/mapping/progress").json()["confirmed"] == 1
        card = client.get(f"/api/cards/{MEGA_LUCARIO[0]}").json()
        assert card["product_catalog_id"] == MEGA_LUCARIO[1]


def test_查無卡種時回404(client):
    assert client.get("/api/cards/999999").status_code == 404


def test_佇列頁提供確認對應與不納入行情(client):
    # Act
    html = client.get("/queue").text

    # Assert：確認對應是一顆獨立按鈕（spec §10.7），不納入行情走 reject（spec §10.9）。
    # 不用「確認對應」「不納入行情」的純字串比對——_app_shell.html 的 showToast
    # 註解裡就寫了這幾個詞，那種斷言在舊版頁面也會空洞地為真。
    assert 'onclick="confirmSelected(this)"' in html
    assert 'onclick="openExclude(this)"' in html
    assert "/api/mapping/confirm" in html
    assert "/api/mapping/reject" in html


def test_不納入行情收在次選單並說明真正的效果(client):
    # Act
    html = client.get("/queue").text

    # Assert：不擺在確認旁邊，收進 ⋯ 次選單（spec §10.9）
    panel = html.split('class="more__panel"', 1)[1]
    assert "不納入行情" in panel.split("</div>", 1)[0]
    # 確認訊息說清楚：不建立行情對應、既有持有品不會被刪除
    assert "不建立" in html and "SNKRDUNK 行情對應" in html
    assert "持有品不會被刪除" in html


def test_佇列頁的已確認歷史以關係呈現且可推翻(client):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")
    _confirm(client, row["id"], MEGA_LUCARIO[0])

    # Act
    html = client.get("/queue").text

    # Assert：以「我的卡種 ↔ SNKRDUNK 卡」呈現（spec §10.11）
    assert "↔" in html
    assert "MEGA Lucario" in html and "メガルカリオ" in html
    # 推翻對應收在 ⋯ 次選單（用 onclick 比對，不用純字串——_app_shell 的註解裡有這個詞），
    # 且確認訊息說明卡種回到待處理、持有品不受影響
    assert 'onclick="openUndo(this)"' in html
    assert "回到待處理" in html
    assert "持有品不受影響" in html
    # 技術 ID 不以資料欄位形式出現在預設畫面（spec §10.11）
    assert str(MEGA_LUCARIO[1]) not in html  # productCatalogId 完全不出現


def test_推翻一個沒有已確認卡種的列回404(client):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")

    # Act
    response = client.delete(f"/api/mapping/confirm/{row['id']}")

    # Assert
    assert response.status_code == 404
    assert client.get("/api/mapping/progress").json()["pending"] == 68
