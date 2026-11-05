"""頁面背景圖：個人檔案、不進 git，圖檔不在時頁面照常顯示深色底。"""

import re


def test_背景圖引用站內local路徑且透明度是變數(client):
    # Act
    css = client.get("/static/design.css").text

    # Assert
    rule = re.search(r"body::before\s*\{(.*?)\}", css, re.S)
    assert rule, "找不到 body::before 規則"
    assert re.search(r'url\("/static/local/background\.\w+"\)', rule.group(1))
    assert "var(--bg-image-opacity)" in rule.group(1)
    assert "pointer-events: none" in rule.group(1)
    assert re.search(r"--bg-image-opacity:\s*[\d.]+", css)


def test_背景圖檔不存在時樣式表與頁面照常回應(client):
    # Act：測試環境沒有 static/local/background.*（它是個人檔案、不進 git）
    css = client.get("/static/design.css")
    page = client.get("/")

    # Assert：缺圖只會讓 url() 載入失敗，不影響 body 的深色底
    assert css.status_code == 200
    assert page.status_code == 200
    assert re.search(r"body\s*\{[^}]*background:\s*var\(--bg-app\)", css.text)


def test_webp靜態檔以圖片類型提供(client):
    # Arrange：app 已被 import（client fixture）。不依賴 static/local/ 的背景圖，
    # 它被 gitignore，測試環境不一定有。StaticFiles 就是靠 mimetypes 猜 Content-Type。
    import mimetypes

    # Act
    guessed, _ = mimetypes.guess_type("/static/local/background.webp")

    # Assert
    assert guessed == "image/webp"


def test_靜態檔每次都向伺服器確認新舊且保留etag(client):
    # Act
    response = client.get("/static/design.css")

    # Assert：no-cache 不是 no-store——可以快取，但用之前要先問；etag 讓沒變動時回 304
    assert response.status_code == 200
    assert "no-cache" in response.headers["cache-control"]
    assert "no-store" not in response.headers["cache-control"]
    assert response.headers["etag"]
    revalidated = client.get(
        "/static/design.css", headers={"If-None-Match": response.headers["etag"]}
    )
    assert revalidated.status_code == 304
