"""背景圖前處理腳本：裁掉四周黑邊、上下邊緣淡成頁面底色，讓 repeat-y 的交界不會硬切。"""

import importlib.util
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIGHT = (200, 150, 100)
BLACK = (0, 0, 0)


def _load_script():
    """scripts/ 不是套件，照檔案路徑載進來。"""
    spec = importlib.util.spec_from_file_location(
        "prepare_background", REPO_ROOT / "scripts" / "prepare_background.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _framed(width: int = 40, height: int = 100, border: int = 2) -> Image.Image:
    image = Image.new("RGB", (width, height), BLACK)
    image.paste(Image.new("RGB", (width - 2 * border, height - 2 * border), BRIGHT), (border, border))
    return image


def test_四周的黑邊被裁掉():
    # Arrange
    script = _load_script()

    # Act
    cropped = script.crop_dark_border(_framed(border=2))

    # Assert：黑邊與緊鄰的過渡列都不留，四個角都是畫面內容
    width, height = cropped.size
    assert width <= 36 and height <= 96
    for corner in [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]:
        assert cropped.getpixel(corner) == BRIGHT


def test_上下邊緣淡成頁面底色而中段不變():
    # Arrange
    script = _load_script()
    image = Image.new("RGB", (10, 100), BRIGHT)

    # Act
    faded = script.fade_edges(image, ratio=0.1)

    # Assert：最上與最下一列就是頁面底色，兩張圖接在一起時交界是同一個顏色
    assert faded.getpixel((5, 0)) == script.PAGE_BACKGROUND
    assert faded.getpixel((5, 99)) == script.PAGE_BACKGROUND
    # 漸層區內愈靠中間愈接近原圖
    assert sum(faded.getpixel((5, 2))) < sum(faded.getpixel((5, 8)))
    # 漸層區以外一個像素都不動
    assert faded.getpixel((5, 50)) == BRIGHT
    assert faded.getpixel((5, 10)) == BRIGHT
    assert faded.getpixel((5, 89)) == BRIGHT


def test_頁面底色與design_css的bg_app一致():
    # Arrange
    script = _load_script()
    css = (REPO_ROOT / "src" / "card_collection" / "static" / "design.css").read_text(encoding="utf-8")

    # Assert：底色改了而腳本沒跟上，交界就會出現一條色差
    red, green, blue = script.PAGE_BACKGROUND
    assert f"--bg-app: #{red:02X}{green:02X}{blue:02X};" in css
