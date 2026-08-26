"""首頁的總覽數字。

這裡**不重算任何金額**——持有品摘要已經算過一遍，首頁再算一次就會有兩套帳。本
模組只做一件摘要沒做的事：補上報酬率。卡圖牆之後長在同一個回應上。
"""

from collections.abc import Mapping


def overview(summary: Mapping) -> dict:
    """在持有品摘要之上補一個未實現報酬率。

    分母只取**有市值的那部分成本**。含進沒有市值的持有品會把報酬率稀釋成一個誰
    也不代表的數字——分子只涵蓋五張卡，分母卻涵蓋八十九張。

    沒有任何持有品算得出市值時，這個欄位**不存在**，不是 0——0 會被讀成「不賺
    不賠」（與持有品摘要對缺市值欄位的處置一致）。
    """
    cost = summary["held_cost_valued_twd"]
    if not cost:
        return dict(summary)
    return {**summary, "unrealized_return_rate": summary["unrealized_pnl_twd"] / cost}
