"""讀取 Notion 匯出的 CSV：推導相異卡種，以及逐列讀出持有品。

CSV 的一列是一筆持有品，不是一個卡種。卡種唯一鍵為系列代碼＋卡號＋卡名
（ADR-0008）——卡號在錯體版與 25 週年特典卡兩種情況下都會重複。
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from .holding_rules import (
    HoldingRuleError,
    check_sold_not_before_purchase,
    check_sold_pair,
    parse_amount,
    parse_date,
)
from .normalization import normalize_card_number, normalize_series


class HoldingImportError(ValueError):
    """來源資料不合格。訊息一律指出來源列號與該列的卡種寫法。

    欄位規則本身住在 `holding_rules`，與 CRUD 共用；這裡只負責把「哪一列」接上去。
    """


@dataclass(frozen=True)
class CardKind:
    series_raw: str
    number_raw: str
    card_name_raw: str
    series_normalized: str
    number_normalized: str


@dataclass(frozen=True)
class HoldingRow:
    """CSV 的一列。原始寫法與正規化值並存，原始值永不改寫。

    持有品沒有天然唯一鍵——欄位完全相同的兩列是兩張實體卡。唯一能識別
    來源的只有列號，所以列號隨著資料一起存下來。
    """

    source_row_number: int
    series_raw: str
    number_raw: str
    card_name_raw: str
    purchase_date: str
    purchase_date_raw: str
    cost_twd: int
    sold_date: str | None
    sold_date_raw: str | None
    sold_price_twd: int | None
    grading_raw: str

    @property
    def kind_key(self) -> tuple[str, str, str]:
        return (self.series_raw, self.number_raw, self.card_name_raw)


def read_card_kinds(csv_path: Path) -> tuple[CardKind, ...]:
    """回傳去重並排序後的卡種。順序穩定，重跑不變。"""
    kinds = {_to_card_kind(holding) for holding in _read_rows(csv_path)}
    return tuple(sorted(kinds, key=_sort_key))


def read_holdings(csv_path: Path) -> tuple[HoldingRow, ...]:
    """逐列讀出持有品，不去重。任何一列不合格就整批失敗。"""
    return tuple(
        _to_holding_row(holding, row_number)
        for row_number, holding in enumerate(_read_rows(csv_path), start=1)
    )


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def _to_holding_row(holding: dict[str, str], row_number: int) -> HoldingRow:
    """規則不合格時，補上是哪一列出的問題再往上丟。

    規則自己不知道它被誰用，所以它給的是一句單獨讀得懂的話；來源列號只有這裡知道。
    """
    try:
        return _build_holding_row(holding, row_number)
    except HoldingRuleError as error:
        raise HoldingImportError(f"{_where(holding, row_number)}：{error}") from error


def _build_holding_row(holding: dict[str, str], row_number: int) -> HoldingRow:
    purchase_date_raw = holding["purchase date"].strip()
    purchase_date = parse_date(purchase_date_raw, "購入日")
    sold_date_raw = holding["sold date"].strip()
    sold_price_raw = holding["sold price"].strip()
    check_sold_pair(sold_date_raw or None, sold_price_raw or None)
    sold_date = parse_date(sold_date_raw, "售出日") if sold_date_raw else None
    if sold_date is not None:
        check_sold_not_before_purchase(sold_date, purchase_date)
    return HoldingRow(
        source_row_number=row_number,
        series_raw=holding["set name"],
        number_raw=holding["card num"],
        card_name_raw=holding["card name"],
        purchase_date=purchase_date.isoformat(),
        purchase_date_raw=purchase_date_raw,
        cost_twd=parse_amount(holding["cost"].strip(), "購入成本"),
        sold_date=sold_date.isoformat() if sold_date else None,
        sold_date_raw=sold_date_raw or None,
        sold_price_twd=(
            parse_amount(sold_price_raw, "售出價") if sold_date else None
        ),
        grading_raw=holding["grading score"],
    )


def _where(holding: dict[str, str], row_number: int) -> str:
    kind = f"{holding['set name']} #{holding['card num']} {holding['card name']}"
    return f"第 {row_number} 列（{kind}）"


def _sort_key(kind: CardKind) -> tuple[str, str, str]:
    return (kind.series_normalized, kind.number_normalized, kind.card_name_raw)
