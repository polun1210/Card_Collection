"""卡圖入庫：下載 SNKRDUNK 的 xl 原圖並裁掉四周留白。

原圖是 1000×730 的去背 WebP，卡片本身只佔畫布中間一小塊（實測 441×610）。
不裁的話，之後卡圖牆上每張卡的實際大小會參差不齊。
"""

import io
from pathlib import Path

from PIL import Image

IMAGE_FORMAT = "WEBP"
IMAGE_SUFFIX = ".webp"
IMAGE_MEDIA_TYPE = "image/webp"
# 來源本身就是有損 WebP，無損保存只是把它的壓縮痕跡也原封存下來——
# 同一張卡 372 KB 對 127 KB，畫質看不出差別。
IMAGE_QUALITY = 95


class CardImageError(RuntimeError):
    """卡圖處理失敗。卡圖是裝飾，失敗不該擋下確認。"""


def crop_border(data: bytes) -> bytes:
    """裁掉去背後四周的透明留白。"""
    try:
        image = Image.open(io.BytesIO(data))
        border = image.getbbox()
        cropped = image.crop(border) if border else image
    except Exception as error:  # Pillow 對壞檔會丟各式各樣的例外
        raise CardImageError(f"卡圖無法解析：{error}") from error
    buffer = io.BytesIO()
    cropped.save(buffer, format=IMAGE_FORMAT, quality=IMAGE_QUALITY)
    return buffer.getvalue()


class CardImageStore:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def path_for(self, apparel_id: int) -> Path:
        return self._directory / f"{apparel_id}{IMAGE_SUFFIX}"

    def save(self, apparel_id: int, data: bytes) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(apparel_id)
        path.write_bytes(crop_border(data))
        return path
