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
