"""候選卡種的外部行為。

斷言一律走 HTTP API；外部 SNKRDUNK 在 httpx 傳輸層回放錄下的真實回應。
"""


def _find(client, series: str, number: str, card_name: str) -> dict:
    rows = client.get("/api/mapping/queue").json()
    matched = [
        row
        for row in rows
        if row["series_raw"] == series
        and row["number_raw"] == number
        and row["card_name_raw"] == card_name
    ]
    assert matched, f"待確認清單應含 {series} {number} {card_name}"
    return matched[0]


def _row(client, series: str, number: str, card_name: str) -> dict:
    """取回該列並補上候選。"""
    row = _find(client, series, number, card_name)
    response = client.post(f"/api/mapping/candidates/{row['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def test_每一列附帶候選清單(client):
    # Act
    row = _row(client, "M2a", "228", "MEGA Lucario")

    # Assert
    assert len(row["candidates"]) == 2


def test_候選含卡圖與英日卡名與卡種代碼(client):
    # Act
    row = _row(client, "M2a", "228", "MEGA Lucario")
    candidate = next(c for c in row["candidates"] if c["apparel_id"] == 722241)

    # Assert
    assert candidate["image_url"].startswith("https://cdn.snkrdunk.com/")
    assert "MEGA Lucario ex MA" in candidate["name_en"]
    assert "メガルカリオ" in candidate["name_ja"]
    assert candidate["card_code"] == "M2a 228/193"


def test_錯體版與正常版撈到同一批候選但各自獨立(client):
    # Act
    normal = _row(client, "M2a", "228", "MEGA Lucario")
    error_card = _row(client, "M2a", "228", "MEGA Lucario Printing Error")

    # Assert：兩列是不同的待確認列，但候選相同——撈到同一批是預期行為
    assert normal["id"] != error_card["id"]
    ids = {c["apparel_id"] for c in normal["candidates"]}
    assert ids == {c["apparel_id"] for c in error_card["candidates"]}
    assert ids == {722241, 744296}


def test_二十五週年特典卡的候選需要人眼分辨(client):
    # Act：S8a 001 兩列共用同一批候選，其中同時有皮卡丘與噴火龍
    row = _row(client, "S8a", "1", "Charizard 25th")
    names = " ".join(c["name_en"] for c in row["candidates"])

    # Assert
    assert len(row["candidates"]) >= 4
    assert "Pikachu" in names and "Charizard" in names


def test_查無候選時回空清單而不報錯(client):
    # Act：CP2 002 沒有錄到搜尋結果，回放的是真實的「查無結果」回應
    row = _row(client, "CP2", "2", "Reshiram")

    # Assert
    assert row["candidates"] == []


def test_候選只向SNKRDUNK取一次(client, snkrdunk):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")

    # Act
    client.post(f"/api/mapping/candidates/{row['id']}")
    first_call_count = len(snkrdunk.requests)
    client.post(f"/api/mapping/candidates/{row['id']}")

    # Assert：第二次不再打外部
    assert first_call_count > 0
    assert len(snkrdunk.requests) == first_call_count


def test_待確認清單本身不打外部(client, snkrdunk):
    # Act
    client.get("/api/mapping/queue")

    # Assert：讀取與抓取分開，列清單不會意外轟炸 SNKRDUNK
    assert snkrdunk.requests == []


def test_SNKRDUNK回非預期結果時明確報錯(client, snkrdunk):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")
    snkrdunk.forced_status = 500

    # Act
    response = client.post(f"/api/mapping/candidates/{row['id']}")

    # Assert：不靜默回空清單
    assert response.status_code >= 500
    assert "SNKRDUNK" in response.json()["detail"]


def test_對SNKRDUNK的請求之間有間隔(client, snkrdunk):
    # Act
    _row(client, "M2a", "228", "MEGA Lucario")

    # Assert：每一次外部請求前都等待，不並發轟炸
    assert len(snkrdunk.sleeps) >= len(snkrdunk.requests) - 1
    assert all(seconds > 0 for seconds in snkrdunk.sleeps)


def test_佇列頁顯示候選卡圖(client):
    # Act
    html = client.get("/queue").text

    # Assert
    assert "https://cdn.snkrdunk.com/" in html
    assert "メガルカリオ" in html


def test_點選候選只選取需再按確認才寫入(client):
    # Act
    html = client.get("/queue").text

    # Assert：點候選走 pickCandidate（只選取），寫入要另按「確認對應」（spec §10.7）
    assert "pickCandidate(this)" in html
    assert "確認對應" in html
    assert 'onclick="confirmSelected(this)"' in html
    # 「確認對應」一開始是停用的——沒選候選就不能確認
    assert "confirm-bar__go" in html and "disabled" in html


def test_搜尋成功零候選與來源失敗在畫面上長得不一樣(client):
    # Arrange：CP2 002 的錄下回應是真實的「查無結果」——搜尋成功、零筆
    reshiram = _find(client, "CP2", "2", "Reshiram")
    assert (
        client.post(f"/api/mapping/candidates/{reshiram['id']}").json()["candidates"]
        == []
    )

    # Act
    html = client.get("/queue").text

    # Assert：搜尋成功但沒人賣 → 中性的「沒有找到候選」，不是來源失敗那個說法
    assert "沒有找到候選" in html
    assert "status-pending cands__state" in html  # 中性狀態樣式
    # 而且畫面上沒有來源失敗的說法與重試入口
    assert "無法取得 SNKRDUNK 候選" not in html
    assert "cands__error" not in html


def test_來源掛掉時卡種對應頁仍然渲染得出來(client, snkrdunk):
    # Arrange：候選抓取整個掛掉（連線中斷）
    snkrdunk.raise_network_error = True

    # Act
    response = client.get("/queue")

    # Assert：整頁不該 500——待處理清單與歷史都還讀得出來（這是真實發生過的當機）
    assert response.status_code == 200, response.text
    html = response.text
    assert "卡種對應" in html
    assert "已確認" in html  # 歷史區塊仍在
    # 抓不到候選的那幾張明確說「無法取得」並提供重試，不冒充成「沒有找到候選」
    assert "無法取得 SNKRDUNK 候選" in html
    assert 'onclick="retryCandidates(this)"' in html  # 重試入口
    assert "沒有找到候選" not in html
    assert "cands__error" in html  # 用錯誤狀態的容器，不是中性的 status-pending


def test_對不存在的列取候選回404(client):
    # Act
    response = client.post("/api/mapping/candidates/999999")

    # Assert
    assert response.status_code == 404


def test_連線失敗時明確報錯(client, snkrdunk):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")
    snkrdunk.raise_network_error = True

    # Act
    response = client.post(f"/api/mapping/candidates/{row['id']}")

    # Assert
    assert response.status_code >= 500
    assert "SNKRDUNK" in response.json()["detail"]


def test_候選缺少卡圖時不靜默收下(client, snkrdunk):
    # Arrange
    row = _find(client, "M2a", "228", "MEGA Lucario")
    snkrdunk.strip_card_image = True

    # Act
    response = client.post(f"/api/mapping/candidates/{row['id']}")

    # Assert：殘缺的候選不進資料庫
    assert response.status_code >= 500
    assert client.get("/api/mapping/queue").json()[0]["candidates"] == []


def test_佇列頁第二次載入不再打外部(client, snkrdunk):
    # Arrange
    client.get("/queue", params={"limit": 14})
    first_call_count = len(snkrdunk.requests)

    # Act
    client.get("/queue", params={"limit": 14})

    # Assert：補的必須是顯示中的那一批，否則每次載入都在抓下一批
    assert first_call_count > 0
    assert len(snkrdunk.requests) == first_call_count
