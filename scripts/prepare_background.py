"""把一張圖整理成頁面背景圖：裁掉四周黑邊、上下邊緣淡成頁面底色、存成 webp。

    uv run python scripts/prepare_background.py C:\\path\\to\\image.png

輸出到 `src/card_collection/static/local/background.webp`（該目錄不進 git，見
docs/interface.md §7.6）。只讀來源圖、只寫這一個輸出檔，不碰網路與資料庫。

為什麼要前處理：背景圖以 `repeat-y` 往下重複（design.css 的 `body::before`），
一張的底部會直接接上下一張的頂部。
- 很多圖四周有 1～2 px 的黑邊，放大好幾倍後兩條接在一起就是一條粗黑線，所以先裁掉。
- 圖的頂部與底部畫的通常是不同的東西，硬接會看得出切口，所以上下各淡成頁面底色，
  交界兩側就是同一個顏色。
"""

import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "src" / "card_collection" / "static" / "local" / "background.webp"

# 必須與 design.css 的 --bg-app 一致，交界才不會有色差（有測試守著）。
PAGE_BACKGROUND = (0x0B, 0x0F, 0x14)
# 一列（或一行）的平均亮度低於這個值就視為黑邊。
DARK_THRESHOLD = 40
# 黑邊與內容之間通常還有一列半黑的過渡，多裁這麼多。
EXTRA_CROP = 1
# 上下各有多少比例的高度用來漸層。
DEFAULT_FADE_RATIO = 0.08
WEBP_QUALITY = 85


def _is_dark(pixels: list[tuple[int, int, int]]) -> bool:
    return sum(sum(pixel) for pixel in pixels) / (3 * len(pixels)) < DARK_THRESHOLD


def crop_dark_border(image: Image.Image) -> Image.Image:
    """裁掉四周的黑邊，回傳新圖，不改動傳入的圖。"""
    rgb = image.convert("RGB")
    width, height = rgb.size

    def row(y: int) -> list[tuple[int, int, int]]:
        return [rgb.getpixel((x, y)) for x in range(width)]

    def column(x: int) -> list[tuple[int, int, int]]:
        return [rgb.getpixel((x, y)) for y in range(height)]

    top = next(y for y in range(height) if not _is_dark(row(y)))
    bottom = next(y for y in reversed(range(height)) if not _is_dark(row(y)))
    left = next(x for x in range(width) if not _is_dark(column(x)))
    right = next(x for x in reversed(range(width)) if not _is_dark(column(x)))

    # 有裁到黑邊的那一側才多裁過渡列；本來就沒黑邊的邊不動。
    return rgb.crop(
        (
            left + (EXTRA_CROP if left > 0 else 0),
            top + (EXTRA_CROP if top > 0 else 0),
            right + 1 - (EXTRA_CROP if right < width - 1 else 0),
            bottom + 1 - (EXTRA_CROP if bottom < height - 1 else 0),
        )
    )


def _smoothstep(t: float) -> float:
    return t * t * (3 - 2 * t)


def fade_edges(image: Image.Image, ratio: float = DEFAULT_FADE_RATIO) -> Image.Image:
    """上下邊緣以 smoothstep 淡成頁面底色，回傳新圖；漸層區以外的像素不動。"""
    rgb = image.convert("RGB")
    width, height = rgb.size
    band = max(1, round(height * ratio))

    mask = Image.new("L", (1, height), 255)
    for offset in range(band):
        level = round(255 * _smoothstep(offset / band))
        mask.putpixel((0, offset), level)
        mask.putpixel((0, height - 1 - offset), level)

    background = Image.new("RGB", rgb.size, PAGE_BACKGROUND)
    return Image.composite(rgb, background, mask.resize(rgb.size))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    source = Path(argv[1])
    prepared = fade_edges(crop_dark_border(Image.open(source)))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    prepared.save(OUTPUT, "WEBP", quality=WEBP_QUALITY)
    print(f"已輸出 {OUTPUT}（{prepared.size[0]}×{prepared.size[1]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
