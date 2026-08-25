"""讀取 Notion 匯出的持有品 CSV，推導出相異卡種。

CSV 的一列是一筆持有品，不是一個卡種。卡種唯一鍵為系列代碼＋卡號＋卡名
（ADR-0008）——卡號在錯體版與 25 週年特典卡兩種情況下都會重複。
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from .normalization import normalize_card_number, normalize_series


@dataclass(frozen=True)
class CardKind:
    series_raw: str
    number_raw: str
    card_name_raw: str
    series_normalized: str
    number_normalized: str


def read_card_kinds(csv_path: Path) -> tuple[CardKind, ...]:
    """回傳去重並排序後的卡種。順序穩定，重跑不變。"""
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        holdings = list(csv.DictReader(handle))
    kinds = {_to_card_kind(holding) for holding in holdings}
    return tuple(sorted(kinds, key=_sort_key))


def _to_card_kind(holding: dict[str, str]) -> CardKind:
    """原始欄位逐字保留，不 strip；收斂只發生在正規化的衍生欄位上。"""
    series_raw = holding["set name"]
    number_raw = holding["card num"]
    return CardKind(
        series_raw=series_raw,
        number_raw=number_raw,
        card_name_raw=holding["card name"],
        series_normalized=normalize_series(series_raw),
        number_normalized=normalize_card_number(number_raw),
    )


def _sort_key(kind: CardKind) -> tuple[str, str, str]:
    return (kind.series_normalized, kind.number_normalized, kind.card_name_raw)
