"""持有品的欄位規則。CSV 匯入與 CRUD 兩條路徑共用同一份。

規則只能有一個地方說了算。兩邊各寫一份必然漂移，而且漂移會**安靜地站在 CRUD 那側**
——CSV 匯入是一次性的（ADR-0013），日後幾乎不會再跑，所以匯入那份規則一旦與 CRUD
分歧，沒有人會發現。

訊息刻意寫成**單獨讀得懂的句子**（「購入成本「0」不是正整數」），由呼叫端依自己的
場景加前綴：匯入加上來源列號，CRUD 直接回給使用者。規則本身不知道自己被誰用。
"""

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
