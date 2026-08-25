"""把 Notion 的自由寫法收斂成可比對的正規化值。

原始值一律另存、永不改寫（原始值優先，見 CONTEXT.md）。
"""

CARD_NUMBER_WIDTH = 3

# Notion 裡同一個系列出現過多種寫法，一律收斂到 SNKRDUNK 的官方寫法。
SERIES_ALIASES = {"SVP": "SV-P"}


def normalize_series(series_raw: str) -> str:
    series = series_raw.strip()
    return SERIES_ALIASES.get(series, series)


def normalize_card_number(number_raw: str) -> str:
    return number_raw.strip().zfill(CARD_NUMBER_WIDTH)
