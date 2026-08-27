"""動能與流動性——市值以外的兩個指標。

市值回答「現在值多少」，這兩個回答「它在動嗎、動得起來嗎」。兩者都可能**算不出
來**，而算不出來與「算出來是 0」是完全不同的兩件事：0 會被讀成「不漲不跌」，那是
把缺資料說成一個結論。因此不可用時一律回一個**帶理由的空狀態**，`return_rate` 這
個欄位根本不存在——不是 null，也不是 0（與持有品摘要對缺市值欄位的處置一致）。

這個空狀態**不是暫時的鷹架**。新買進的卡種永遠會經歷「還沒有動能」的階段，資料
補齊之後它依然存在，因此它得長得像刻意的設計，而不是壞掉的畫面。
"""

from collections.abc import Sequence
from datetime import date
from statistics import median

# 兩個視窗各 30 天：近 30 天（第 0–30 天）與前 30 天（第 31–60 天）。窗口長度與市值
# 刻意相同（ADR-0002）——動能就是「這一期的成交價中位數相對上一期」，不是別的定義。
MOMENTUM_WINDOW_DAYS = 30

REASON_NO_RECENT = "近 30 天沒有成交紀錄，算不出這一期的中位數"
REASON_NO_PREVIOUS = "前 30 天（第 31–60 天）沒有成交紀錄，沒有可比的基準"
# 兩個半邊都還不到位，而 CONTEXT.md 明文規定兩者分開看沒有意義、必須並列，
# 因此不先開熱門度那一半——半個流動性比沒有流動性更容易被讀錯。
REASON_LIQUIDITY_PENDING = (
    "PSA 10 張數還沒有資料來源（ADR-0005 走 PriceCharting，尚未實作），"
    "熱門度則受 SNKRDUNK 成交明細 20 筆上限低估。"
    "存世多但成交少，與存世多且成交多是完全不同的兩張卡，"
    "所以兩個數字必須並列，不先開其中一半。"
)


def momentum(sales: Sequence[dict], today: date) -> dict:
    """近 30 天成交價中位數相對前 30 天的報酬率。

    兩個視窗任一為空就不算。**不放寬窗口去湊資料**——那會讓「動能」變成浮動定義，
    今天的 −5% 與上週的 −5% 就不再是同一件事。

    原料與市值同一份：待審的成交紀錄一律不參與（由呼叫端負責只傳參與計算的）。
    """
    recent = _window(sales, today, 0, MOMENTUM_WINDOW_DAYS)
    previous = _window(
        sales, today, MOMENTUM_WINDOW_DAYS + 1, MOMENTUM_WINDOW_DAYS * 2
    )
    if not recent:
        return {"available": False, "reason": REASON_NO_RECENT}
    if not previous:
        return {"available": False, "reason": REASON_NO_PREVIOUS}
    before = median(previous)
    return {
        "available": True,
        # 全站唯一的報酬率定義：(結果 − 成本) ÷ 成本，不使用倍數。
        "return_rate": (median(recent) - before) / before,
        # 樣本形狀與市值旁的樣本筆數同一個道理（ADR-0015）：一個由兩筆成交撐起來
        # 的 +30%，與由二十筆撐起來的 +30%，不該長得一模一樣。
        "recent_count": len(recent),
        "previous_count": len(previous),
    }


def _window(
    sales: Sequence[dict], today: date, from_days_ago: int, to_days_ago: int
) -> list[int]:
    """第 from…to 天（含兩端）之間的成交價，單位新台幣。"""
    prices = []
    for sale in sales:
        age = (today - date.fromisoformat(sale["sold_date_jst"])).days
        if from_days_ago <= age <= to_days_ago:
            prices.append(sale["price_twd"])
    return prices


def liquidity() -> dict:
    """恆為不可用。兩個半邊都還沒有來源，理由一起帶著，不留一塊空白給人猜。"""
    return {"available": False, "reason": REASON_LIQUIDITY_PENDING}
