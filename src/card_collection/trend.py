"""走勢圖：逐日的總市值與總成本，外加當天的涵蓋率。

**不新增任何快照表，逐日即時計算。** 市值的定義只有一個（ADR-0002），把歷史日期
餵進同一個函式，算出來的就是那一天的市值。存一份快照就是存第二套帳，而第二套帳
必然與定義漂移——漂移的方向還是安靜的那一邊。

兩條紀律撐起「昨天截圖存下的圖，今天仍然對得上」：

- **該日實際持有**：購入日 ≤ 該日，且（未售出 或 售出日 > 該日）。賣出一張卡不
  會回頭改寫整條歷史曲線（ADR-0003）。
- **只餵該日（含）以前的成交紀錄**。這一步必須明確做，不能倚賴市值函式的 30 天
  視窗順手擋掉——那個視窗擋得住三十天前的過去，擋不住未來。

每一個點都並列「算得出市值的持有卡種數」與「總持有卡種數」（ADR-0021）。
"""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from datetime import date, timedelta

from .sales import MARKET_VALUE_WINDOW_DAYS, market_value

_WINDOW = timedelta(days=MARKET_VALUE_WINDOW_DAYS)


def daily_trend(
    holdings: Sequence[dict],
    sales_by_apparel: dict[int, list[dict]],
    today: date,
) -> tuple[dict, ...]:
    """自有東西可看的第一天至今日，逐日一個點，中間不留斷點。

    包含沒有任何成交發生的日子——市值本來就有「近 30 天無成交沿用最後市值」的
    規則，曲線因此是連續的，而不是一串孤立的成交日。

    成交紀錄或持有品其中一邊是空的時就回空的：畫不出來就說畫不出來，不編一條線
    出來。
    """
    history = {
        apparel_id: (sales, [sale["sold_date_jst"] for sale in sales])
        for apparel_id, sales in sales_by_apparel.items()
        if sales
    }
    day = _first_day(holdings, history)
    if day is None:
        return ()
    points = []
    while day <= today:
        points.append(_point(day, holdings, history))
        day += timedelta(days=1)
    return tuple(points)


def spans_a_year(points: Sequence[dict]) -> bool:
    """曲線的總跨度是否滿一年。

    曲線逐日連續，所以點數就是天數——不必再把兩端的日期解析回來相減。
    """
    return len(points) > 365


def _first_day(
    holdings: Sequence[dict], history: dict[int, tuple[list[dict], list[str]]]
) -> date | None:
    """曲線的起點：最早成交紀錄日與最早購入日的**較晚者**。

    兩邊都得有東西，那一天才畫得出點。比最早購入日還早的成交紀錄，那幾天一張卡
    都沒持有，兩條線都貼在 0；比最早成交紀錄還早的購入日，那幾天一個卡種也估不
    出價。兩種都是有寬度、沒資訊的留白，只會把真正要看的那一段擠窄。
    """
    sale_days = [days[0] for _, days in history.values()]
    if not sale_days or not holdings:
        return None
    return max(
        date.fromisoformat(min(sale_days)),
        date.fromisoformat(min(holding["purchase_date"] for holding in holdings)),
    )


def _point(day: date, holdings: Sequence[dict], history: dict) -> dict:
    """某一天的總市值、總成本與涵蓋率。

    市值以**卡種**為單位算一次，再依該日持有幾張加總——同一個卡種持有三張，市值
    就進去三次，與持有品摘要的加總方式一致。
    """
    iso = day.isoformat()
    held = [holding for holding in holdings if _held_on(holding, iso)]
    values: dict[int, int | None] = {}
    for holding in held:
        kind = holding["mapping_candidate_id"]
        if kind not in values:
            values[kind] = _value_on(history, holding["apparel_id"], day)
    return {
        "date": iso,
        # 算不出市值的卡種不進總和，但它下面那幾張的成本照算——這兩個數字涵蓋的
        # 範圍不同，涵蓋率就是拿來說明這件事的。
        "market_value_twd": sum(
            value
            for holding in held
            if (value := values[holding["mapping_candidate_id"]]) is not None
        ),
        "cost_twd": sum(holding["cost_twd"] for holding in held),
        "valued_kind_count": sum(1 for value in values.values() if value is not None),
        "held_kind_count": len(values),
    }


def _held_on(holding: dict, iso: str) -> bool:
    """售出日當天起就不再是「該日實際持有」——那一天它已經換手了。"""
    return holding["purchase_date"] <= iso and (
        holding["sold_date"] is None or holding["sold_date"] > iso
    )


def _value_on(history: dict, apparel_id: int | None, day: date) -> int | None:
    """該卡種在該日的市值。尚未對應或該日之前毫無成交的，回 None 而不是 0。

    只把**可能落進視窗**的那一段交給市值函式：視窗最遠回推 30 天，更舊的成交無論
    如何都不會進樣本。曲線是逐日重算的，本地成交紀錄又逐日累積，不切這一刀的話，
    每多跑一天，整張圖就多算一份用不上的舊資料。
    """
    entry = history.get(apparel_id)
    if entry is None:
        return None
    sales, days = entry
    end = bisect_right(days, day.isoformat())
    if not end:
        return None
    oldest_in_window = (date.fromisoformat(days[end - 1]) - _WINDOW).isoformat()
    value = market_value(sales[bisect_left(days, oldest_in_window) : end], day)
    return None if value is None else value["market_value_twd"]
