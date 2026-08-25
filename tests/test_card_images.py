"""卡圖入庫與對照清單的外部行為。"""

import csv
import io

MEGA_LUCARIO = 722241
PRINTING_ERROR = 744296
ORIGINAL_SIZE = (1000, 730)


def _find(client, series: str, number: str, card_name: str) -> dict | None:
    for row in client.get("/api/mapping/queue").json():
        if (
            row["series_raw"] == series
            and row["number_raw"] == number
            and row["card_name_raw"] == card_name
        ):
            return row
    return None


def _confirm_mega_lucario(client) -> dict:
    row = _find(client, "M2a", "228", "MEGA Lucario")
    response = client.post(
        "/api/mapping/confirm",
        json={"mapping_candidate_id": row["id"], "apparel_id": MEGA_LUCARIO},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_確認後卡種帶著本機卡圖路徑(client):
    # Act
    card = _confirm_mega_lucario(client)

    # Assert
    assert card["image_local_path"]
    assert client.get(f"/api/cards/{MEGA_LUCARIO}").json()["image_local_path"]


def test_卡圖四周留白被裁掉(client):
    # Arrange
    from PIL import Image

    _confirm_mega_lucario(client)

    # Act
    response = client.get(f"/api/cards/{MEGA_LUCARIO}/image")

    # Assert
    assert response.status_code == 200
    cropped = Image.open(io.BytesIO(response.content))
    assert cropped.size[0] < ORIGINAL_SIZE[0]
    assert cropped.size[1] < ORIGINAL_SIZE[1]


def test_卡圖下載失敗時確認仍然成功並標記缺失(client, snkrdunk):
    # Arrange
    snkrdunk.image_download_fails = True

    # Act
    card = _confirm_mega_lucario(client)

    # Assert：productCatalogId 才是命脈，卡圖只是裝飾
    assert card["product_catalog_id"] == 834208
    assert card["image_local_path"] is None
    assert client.get(f"/api/cards/{MEGA_LUCARIO}/image").status_code == 404


def test_卡圖缺失可事後補圖不需推翻確認(client, snkrdunk):
    # Arrange
    snkrdunk.image_download_fails = True
    _confirm_mega_lucario(client)
    snkrdunk.image_download_fails = False

    # Act
    response = client.post(f"/api/cards/{MEGA_LUCARIO}/image")

    # Assert
    assert response.status_code == 200
    assert client.get(f"/api/cards/{MEGA_LUCARIO}").json()["image_local_path"]
    assert client.get(f"/api/cards/{MEGA_LUCARIO}/image").status_code == 200


def test_補圖時仍失敗則明確報錯(client, snkrdunk):
    # Arrange
    snkrdunk.image_download_fails = True
    _confirm_mega_lucario(client)

    # Act
    response = client.post(f"/api/cards/{MEGA_LUCARIO}/image")

    # Assert
    assert response.status_code >= 500
    assert client.get(f"/api/cards/{MEGA_LUCARIO}").json()["image_local_path"] is None


def test_對照清單含Notion原始寫法與兩個id(client):
    # Arrange
    _confirm_mega_lucario(client)

    # Act
    response = client.get("/api/mapping/export.csv")

    # Assert
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1
    row = rows[0]
    assert (row["series_raw"], row["number_raw"], row["card_name_raw"]) == (
        "M2a",
        "228",
        "MEGA Lucario",
    )
    assert row["apparel_id"] == str(MEGA_LUCARIO)
    assert row["product_catalog_id"] == "834208"
    assert "MEGA Lucario ex MA" in row["name_en"]
    assert "メガルカリオ" in row["name_ja"]


def test_全部處理完後待處理歸零(client):
    # Arrange：兩列確認到不同 apparel，其餘全部否決
    normal = _find(client, "M2a", "228", "MEGA Lucario")
    error_card = _find(client, "M2a", "228", "MEGA Lucario Printing Error")
    client.post("/api/mapping/confirm",
                json={"mapping_candidate_id": normal["id"], "apparel_id": MEGA_LUCARIO})
    client.post("/api/mapping/confirm",
                json={"mapping_candidate_id": error_card["id"], "apparel_id": PRINTING_ERROR})

    # Act
    for row in client.get("/api/mapping/queue").json():
        client.post("/api/mapping/reject", json={"mapping_candidate_id": row["id"]})

    # Assert
    assert client.get("/api/mapping/progress").json() == {
        "confirmed": 2, "rejected": 68, "pending": 0
    }
    assert client.get("/api/mapping/queue").json() == []


def test_首頁的已確認卡種顯示本機卡圖(client):
    # Arrange
    _confirm_mega_lucario(client)

    # Act
    html = client.get("/").text

    # Assert
    assert f"/api/cards/{MEGA_LUCARIO}/image" in html
    assert "對照清單" in html


def test_對不在主檔的卡種補圖回報錯誤(client):
    # Act
    response = client.post("/api/cards/999999/image")

    # Assert
    assert response.status_code >= 500
    assert "999999" in response.json()["detail"]


def test_下載到的檔案不是圖片時確認仍成功但卡圖缺失(client, snkrdunk):
    # Arrange
    snkrdunk.image_is_corrupt = True

    # Act
    card = _confirm_mega_lucario(client)

    # Assert：壞檔不進卡圖庫，也不擋下確認
    assert card["product_catalog_id"] == 834208
    assert card["image_local_path"] is None
    assert client.get(f"/api/cards/{MEGA_LUCARIO}/image").status_code == 404
