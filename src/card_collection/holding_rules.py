"""持有品的欄位規則。CSV 匯入與 CRUD 兩條路徑共用同一份。

規則只能有一個地方說了算。兩邊各寫一份必然漂移，而且漂移會**安靜地站在 CRUD 那側**
——CSV 匯入是一次性的（ADR-0013），日後幾乎不會再跑，所以匯入那份規則一旦與 CRUD
分歧，沒有人會發現。

訊息刻意寫成**單獨讀得懂的句子**（「購入成本「0」不是正整數」），由呼叫端依自己的
場景加前綴：匯入加上來源列號，CRUD 直接回給使用者。規則本身不知道自己被誰用。
"""

from dataclasses import dataclass
from datetime import date, datetime

DATE_FORMATS = ("%Y/%m/%d", "%Y-%m-%d")


class HoldingRuleError(ValueError):
    """欄位不合規則。訊息不含來源脈絡，由呼叫端補上。"""


def parse_date(value: str, label: str) -> date:
    """接受 `2026/3/15` 與 `2026-03-15` 兩種寫法，其餘一律拒絕。

    不猜測「去年三月」這類寫法。猜錯一次就是一筆日期錯誤的持有品，而且看不出來。
    """
    if not value:
        raise HoldingRuleError(f"沒有{label}")
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise HoldingRuleError(f"{label}「{value}」無法解析為日期")


def parse_amount(value: str, label: str) -> int:
    """金額一律為新台幣正整數。0 與負數都不是合法的成本或售價。"""
    if not value.isdigit() or int(value) <= 0:
        raise HoldingRuleError(f"{label}「{value}」不是正整數")
    return int(value)


def check_sold_pair(sold_date: object | None, sold_price: object | None) -> None:
    """售出日與售出價必須同時有值或同時沒有。

    只有其中一個有值時，狀態就說不清楚了：持有中／已售出一律看售出日是否有值
    （ADR-0009），但一筆「有售出價卻沒有售出日」的資料會被判成持有中，那個售出價
    則永遠不會被任何人看見。
    """
    if sold_date is not None and sold_price is None:
        raise HoldingRuleError("有售出日卻沒有售出價")
    if sold_price is not None and sold_date is None:
        raise HoldingRuleError("有售出價卻沒有售出日")


def check_sold_not_before_purchase(sold_date: date, purchase_date: date) -> None:
    """賣在買之前是時間顛倒，不是一種可以被接受的資料。"""
    if sold_date < purchase_date:
        raise HoldingRuleError(
            f"售出日 {sold_date.isoformat()} 早於購入日 {purchase_date.isoformat()}"
        )


def check_not_in_future(value: date, label: str, today: date) -> None:
    """未來的日期多半是打錯年份，當場擋下來比事後查帳容易得多。

    匯入路徑目前不套用這條——它讀的是歷史資料，且沒有時鐘可用。這條規則是為了
    CRUD 而存在的：手動輸入才會打錯年份。
    """
    if value > today:
        raise HoldingRuleError(f"{label} {value.isoformat()} 在未來")


@dataclass(frozen=True)
class HoldingFields:
    """一筆持有品的可寫欄位，全部驗證過。

    原始寫法與正規化值並存（原始值優先）：CRUD 路徑同樣遵守，使用者輸入什麼就存
    什麼，正規化後的日期另存。
    """

    purchase_date: str
    purchase_date_raw: str
    cost_twd: int
    sold_date: str | None
    sold_date_raw: str | None
    sold_price_twd: int | None


def validate(
    purchase_date_raw: str | None,
    cost_twd: object,
    sold_date_raw: str | None,
    sold_price_twd: object | None,
    today: date,
) -> HoldingFields:
    """把一筆持有品的完整欄位驗證成可以寫進資料庫的形狀。

    **驗證的一律是合併後的完整結果，不是這次改動的那幾個欄位。** 否則部分更新就
    成了繞過規則的後門——只改售出日不改售出價，兩個欄位單獨看都沒問題，合起來
    卻是一筆狀態說不清楚的資料。
    """
    if not purchase_date_raw:
        raise HoldingRuleError("沒有購入日")
    purchase_date = parse_date(purchase_date_raw, "購入日")
    check_not_in_future(purchase_date, "購入日", today)

    if cost_twd is None:
        raise HoldingRuleError("沒有購入成本")
    cost = parse_amount(str(cost_twd), "購入成本")

    check_sold_pair(sold_date_raw or None, sold_price_twd)
    if not sold_date_raw:
        return HoldingFields(
            purchase_date=purchase_date.isoformat(),
            purchase_date_raw=purchase_date_raw,
            cost_twd=cost,
            sold_date=None,
            sold_date_raw=None,
            sold_price_twd=None,
        )

    sold_date = parse_date(sold_date_raw, "售出日")
    check_sold_not_before_purchase(sold_date, purchase_date)
    return HoldingFields(
        purchase_date=purchase_date.isoformat(),
        purchase_date_raw=purchase_date_raw,
        cost_twd=cost,
        sold_date=sold_date.isoformat(),
        sold_date_raw=sold_date_raw,
        sold_price_twd=parse_amount(str(sold_price_twd), "售出價"),
    )


# 送進來的是日期的原始寫法，存進去的也是——原始值優先，正規化值另存。
_CHANGEABLE = {
    "purchase_date": "purchase_date_raw",
    "cost_twd": "cost_twd",
    "sold_date": "sold_date_raw",
    "sold_price_twd": "sold_price_twd",
}


def merge(existing: dict, changes: dict) -> dict:
    """部分更新：沒提到的鍵沿用舊值，明確給 None 的鍵就是清空。

    分得出「沒提到」與「設成空」是這裡的全部重點——把誤標的售出改回持有中，靠的
    正是明確送出 null。
    """
    merged = {
        "purchase_date_raw": existing["purchase_date_raw"],
        "cost_twd": existing["cost_twd"],
        "sold_date_raw": existing["sold_date_raw"],
        "sold_price_twd": existing["sold_price_twd"],
    }
    for field, value in changes.items():
        target = _CHANGEABLE.get(field)
        if target is not None:
            merged[target] = value
    return merged
