"""首頁的卡圖牆：一格一個卡種，用認圖的方式找卡。

**不重算任何金額**——每一格的數字都由持有品摘要（`summarize`）算出，與全站總計同
一套帳。本模組自己做的只有分組、排序，與「這一格的報酬率」。

同一個卡種可以同時出現在兩組裡：賣掉兩張、還持有五張是正常狀態，不是錯誤。因此
分組一律**先依狀態、再依卡種**，不是先分卡種再看它是什麼狀態。
"""

from collections.abc import Sequence

from .holdings import STATUS_HELD, STATUS_SOLD, summarize
from .portfolio import overview


def card_wall(holdings: Sequence[dict]) -> dict:
    """持有中與已售出兩組，各自排好序。"""
    return {
        "held": _held_cells(holdings),
        "sold": _sold_cells(holdings),
    }


def _held_cells(holdings: Sequence[dict]) -> list[dict]:
    """最貴的卡先進入視線。沒有市值的卡種排在最後，但**仍然在牆上**。

    沒有市值不會讓一個卡種消失——消失會被讀成「我少了一張卡」，那比一格沒有數字
    嚴重得多。排序用的市值缺席時當 0，剛好把它們排到最後。
    """
    cells = [_held_cell(rows) for rows in _by_kind(holdings, STATUS_HELD).values()]
    return sorted(cells, key=lambda cell: -cell.get("held_market_value_twd", 0))


def _held_cell(rows: Sequence[dict]) -> dict:
    """漲跌幅以**總成本對總市值**計算，不是各張報酬率的平均。

    平均會讓便宜的那張說話特別大聲；總對總才代表你在這個卡種上的實際處境。這正是
    `summarize` ＋ `overview` 對全站做的事，這裡只是把範圍縮到一個卡種。
    """
    summary = overview(summarize(rows))
    cell = {
        **_identity(rows[0]),
        "held_count": summary["held_count"],
        "held_cost_twd": summary["held_cost_twd"],
        # 展開後要逐張列出個別成本：一格是一個卡種，但成本是一張一張付的。
        "holdings": [
            {"purchase_date": row["purchase_date"], "cost_twd": row["cost_twd"]}
            for row in rows
        ],
    }
    # 同一個卡種的持有品共用同一個市值，沒有市值時整組都沒有。
    value = rows[0].get("market_value")
    if value is None:
        return cell
    return {
        **cell,
        # 樣本筆數與涵蓋期間在這裡面，市值旁永遠並列（ADR-0015）。
        "market_value": value,
        "held_market_value_twd": summary["held_market_value_twd"],
        "unrealized_pnl_twd": summary["unrealized_pnl_twd"],
        "return_rate": summary["unrealized_return_rate"],
    }


def _sold_cells(holdings: Sequence[dict]) -> list[dict]:
    """賣得最近的排最前面。這些數字是終局的，不需要展開也不會再變。"""
    cells = [_sold_cell(rows) for rows in _by_kind(holdings, STATUS_SOLD).values()]
    return sorted(cells, key=lambda cell: cell["sold_date"], reverse=True)


def _sold_cell(rows: Sequence[dict]) -> dict:
    summary = summarize(rows)
    # 已售出的成本沒有第二處在算——`summarize` 的持有成本刻意只涵蓋持有中。
    cost = sum(row["cost_twd"] for row in rows)
    realized = summary["realized_pnl_twd"]
    return {
        **_identity(rows[0]),
        "sold_count": summary["sold_count"],
        # 分批賣出時取最近一次：這一格在牆上的位置由它決定。
        "sold_date": max(row["sold_date"] for row in rows),
        "sold_cost_twd": cost,
        "realized_pnl_twd": realized,
        # 與全站同一個報酬率定義：(結果 − 成本) ÷ 成本，不使用倍數。
        "return_rate": realized / cost,
    }


def _by_kind(holdings: Sequence[dict], status: str) -> dict[tuple, list[dict]]:
    """同一狀態的持有品依卡種分組。清單本身已排序，組內順序即為穩定順序。"""
    grouped: dict[tuple, list[dict]] = {}
    for holding in holdings:
        if holding["status"] != status:
            continue
        key = (
            holding["series_raw"],
            holding["number_raw"],
            holding["card_name_raw"],
        )
        grouped.setdefault(key, []).append(holding)
    return grouped


def _identity(holding: dict) -> dict:
    """卡種的身分含卡名（ADR-0008），外加取卡圖用的 apparel id。"""
    return {
        "series_raw": holding["series_raw"],
        "number_raw": holding["number_raw"],
        "card_name_raw": holding["card_name_raw"],
        "apparel_id": holding["apparel_id"],
    }
