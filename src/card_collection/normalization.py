"""把 Notion 的自由寫法收斂成可比對的正規化值。

原始值一律另存、永不改寫（原始值優先，見 CONTEXT.md）。
"""

CARD_NUMBER_WIDTH = 3


def normalize_series(series_raw: str) -> str:
    """系列代碼原樣使用，只去除前後空白——**不做任何代碼收斂**。

    系列代碼本身就決定語言（見 CONTEXT.md）。`SVP`（英文版 Scarlet &
    Violet Promo）與 `SV-P`（日文版促銷卡）是兩個不同語言的不同系列，
    把前者收斂成後者，會讓英文版卡被當成日版卡去估價——而且不會報錯。
    """
    return series_raw.strip()


def normalize_card_number(number_raw: str) -> str:
    return number_raw.strip().zfill(CARD_NUMBER_WIDTH)
