"""讀取 Notion 匯出的 CSV：推導相異卡種，以及逐列讀出持有品。

CSV 的一列是一筆持有品，不是一個卡種。卡種唯一鍵為系列代碼＋卡號＋卡名
（ADR-0008）——卡號在錯體版與 25 週年特典卡兩種情況下都會重複。
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .normalization import normalize_card_number, normalize_series

DATE_FORMATS = ("%Y/%m/%d", "%Y-%m-%d")


class HoldingImportError(ValueError):
    """來源資料不合格。訊息一律指出來源列號與該列的卡種寫法。"""


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
    where = _where(holding, row_number)
    purchase_date_raw = holding["purchase date"].strip()
    purchase_date = _parse_date(purchase_date_raw, "購入日", where)
    sold_date_raw = holding["sold date"].strip()
    sold_price_raw = holding["sold price"].strip()
    sold_date = _parse_sold_date(sold_date_raw, sold_price_raw, purchase_date, where)
    return HoldingRow(
        source_row_number=row_number,
        series_raw=holding["set name"],
        number_raw=holding["card num"],
        card_name_raw=holding["card name"],
        purchase_date=purchase_date.isoformat(),
        purchase_date_raw=purchase_date_raw,
        cost_twd=_parse_amount(holding["cost"].strip(), "購入成本", where),
        sold_date=sold_date.isoformat() if sold_date else None,
        sold_date_raw=sold_date_raw or None,
        sold_price_twd=(
            _parse_amount(sold_price_raw, "售出價", where) if sold_date else None
        ),
        grading_raw=holding["grading score"],
    )


def _parse_sold_date(
    sold_date_raw: str, sold_price_raw: str, purchase_date: date, where: str
) -> date | None:
    """持有中／已售出一律看售出日是否有值，不看售出價（ADR-0009）。"""
    if not sold_date_raw and not sold_price_raw:
        return None
    if not sold_price_raw:
        raise HoldingImportError(f"{where}有售出日卻沒有售出價")
    if not sold_date_raw:
        raise HoldingImportError(f"{where}有售出價卻沒有售出日")
    sold_date = _parse_date(sold_date_raw, "售出日", where)
    if sold_date < purchase_date:
        raise HoldingImportError(
            f"{where}的售出日 {sold_date.isoformat()} "
            f"早於購入日 {purchase_date.isoformat()}"
        )
    return sold_date


def _parse_date(value: str, label: str, where: str) -> date:
    if not value:
        raise HoldingImportError(f"{where}沒有{label}")
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise HoldingImportError(f"{where}的{label}「{value}」無法解析為日期")


def _parse_amount(value: str, label: str, where: str) -> int:
    """金額一律為新台幣正整數。0 與負數都不是合法的成本或售價。"""
    if not value.isdigit() or int(value) <= 0:
        raise HoldingImportError(f"{where}的{label}「{value}」不是正整數")
    return int(value)


def _where(holding: dict[str, str], row_number: int) -> str:
    kind = f"{holding['set name']} #{holding['card num']} {holding['card name']}"
    return f"第 {row_number} 列（{kind}）"


def _sort_key(kind: CardKind) -> tuple[str, str, str]:
    return (kind.series_normalized, kind.number_normalized, kind.card_name_raw)
