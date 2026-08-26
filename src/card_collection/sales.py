"""成交紀錄的讀寫，以及由它衍生的市值。

成交紀錄不對使用者顯示，它是市值的原料（見 CONTEXT.md）。三條紀律：

- **原幣不可變更**：`price_jpy` 與 SNKRDUNK 的原始狀態、枚数文字一律原樣保存。
- **日期一律以 JST 為準**：`soldAt` 是 UTC，同一筆成交在兩個時區會差一天。
- **待審不參與任何計算**：可疑資料一律擋在中位數之外，並附上擋下來的理由。
"""

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import median

from .snkrdunk import Trade

JST = timezone(timedelta(hours=9))
PSA10_CONDITION_NAME = "PSA10"
MARKET_VALUE_WINDOW_DAYS = 30

STATUS_ACTIVE = "active"
STATUS_QUARANTINED = "quarantined"

QUARANTINE_MULTI_PACK = "多張一組，不是單張"
QUARANTINE_NOT_PSA10 = "狀態不是 PSA 10"
# 兩種都與匯率有關，但成因完全不同，畫面上必須分得出來：
# 前者是這一輪根本沒拿到牌告（外部暫時故障），後者是該日期超出來源涵蓋範圍。
QUARANTINE_FX_SOURCE_DOWN = "匯率來源暫時不可用"
QUARANTINE_NO_FX_RATE = "查無成交當日匯率"
# 兩者都會在下一輪爬取自動重試換算（ADR-0016）。
RETRYABLE_FX_REASONS = (QUARANTINE_FX_SOURCE_DOWN, QUARANTINE_NO_FX_RATE)

_SALE_COLUMNS = """
       sale.id,
       sale.apparel_id,
       sale.sold_at_raw,
       sale.sold_date_jst,
       sale.price_jpy,
       sale.price_twd,
       sale.condition_raw,
       sale.variant_raw,
       sale.fx_rate,
       sale.fx_rate_date,
       sale.fx_source,
       sale.status,
       sale.quarantine_reason,
       sale.fetched_at
"""
_SELECT_SALE = f"SELECT {_SALE_COLUMNS} FROM sale"


def to_jst_date(sold_at_raw: str) -> str:
    """`soldAt` 為 UTC，成交日一律換算為日本時間再取日期（ADR-0007）。"""
    return datetime.fromisoformat(sold_at_raw).astimezone(JST).date().isoformat()


@dataclass(frozen=True)
class PendingSale:
    """準備寫入的一筆成交。待審與否在寫入前就決定，理由一起帶著。"""

    apparel_id: int
    sold_at_raw: str
    sold_date_jst: str
    price_jpy: int
    condition_raw: str
    variant_raw: str
    duplicate_index: int
    quarantine_reason: str | None

    @property
    def status(self) -> str:
        return STATUS_ACTIVE if self.quarantine_reason is None else STATUS_QUARANTINED


def to_pending_sales(
    apparel_id: int, trades: Sequence[Trade]
) -> tuple[PendingSale, ...]:
    """把一次抓回來的成交轉成待寫入的列，並編上同批次內的重複序號。

    完全相同的成交（同秒、同價、同枚数）確實存在——實測有一組五筆。唯一鍵若不含
    序號，五筆真實成交會被去重成一筆，熱門度就少算了。
    """
    seen: dict[tuple[str, int, str], int] = {}
    pending = []
    for trade in trades:
        key = (trade.sold_at_raw, trade.price_jpy, trade.variant_raw)
        duplicate_index = seen.get(key, 0)
        seen[key] = duplicate_index + 1
        pending.append(
            PendingSale(
                apparel_id=apparel_id,
                sold_at_raw=trade.sold_at_raw,
                sold_date_jst=to_jst_date(trade.sold_at_raw),
                price_jpy=trade.price_jpy,
                condition_raw=trade.condition_raw,
                variant_raw=trade.variant_raw,
                duplicate_index=duplicate_index,
                quarantine_reason=_quarantine_reason(trade),
            )
        )
    return tuple(pending)


def _quarantine_reason(trade: Trade) -> str | None:
    """來源端的篩選已排掉大部分，這裡是最後一道——篩選失效時不會安靜地混進來。"""
    if not trade.is_single_card:
        return QUARANTINE_MULTI_PACK
    if trade.condition_raw.replace(" ", "").upper() != PSA10_CONDITION_NAME:
        return QUARANTINE_NOT_PSA10
    return None


def market_value(sales: Sequence[dict], today: date) -> dict | None:
    """近 30 天成交紀錄的中位數（ADR-0002），一律附上樣本形狀（ADR-0015）。

    近 30 天無成交時沿用最後一次算得出的市值，並標註過期天數。**不放寬窗口去湊
    資料**——那會讓「市值」變成浮動定義。從未抓到成交的卡種回 None，不編數字。
    """
    if not sales:
        return None
    window = timedelta(days=MARKET_VALUE_WINDOW_DAYS)
    dated = sorted(
        (date.fromisoformat(row["sold_date_jst"]), index, row)
        for index, row in enumerate(sales)
    )
    newest = dated[-1][0]
    window_end = today if newest >= today - window else newest
    sample = [
        (day, row) for day, _, row in dated if window_end - window <= day <= window_end
    ]
    value = {
        "market_value_twd": round(median(row["price_twd"] for _, row in sample)),
        "sample_count": len(sample),
        "sample_from": sample[0][0].isoformat(),
        "sample_to": sample[-1][0].isoformat(),
        "as_of": window_end.isoformat(),
    }
    if window_end != today:
        # 「近 30 天無成交」與「有成交但樣本只涵蓋兩天」是兩種不同的不完整，
        # 只有前者帶過期天數。過期天數恆為正，0 不會被誤讀成「今天的價」。
        value["stale_days"] = (today - newest).days
    return value


def market_values(
    sales_by_apparel: dict[int, list[dict]], today: date
) -> dict[int, dict]:
    """全站一次算完。全站只有這一個市值定義，不會有第二處各算各的。"""
    values = {}
    for apparel_id, sales in sales_by_apparel.items():
        value = market_value(sales, today)
        if value is not None:
            values[apparel_id] = value
    return values


class SaleRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert_many(self, sales: Iterable[PendingSale], fetched_at: str) -> int:
        """重複爬取不重複寫入：唯一鍵含同批次內的重複序號。回傳實際新增筆數。"""
        rows = list(sales)
        if not rows:
            return 0
        before = self._count()
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO sale
                    (apparel_id, sold_at_raw, sold_date_jst, price_jpy, condition_raw,
                     variant_raw, duplicate_index, status, quarantine_reason, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (apparel_id, sold_at_raw, price_jpy, variant_raw,
                             duplicate_index) DO NOTHING
                """,
                [
                    (
                        sale.apparel_id,
                        sale.sold_at_raw,
                        sale.sold_date_jst,
                        sale.price_jpy,
                        sale.condition_raw,
                        sale.variant_raw,
                        sale.duplicate_index,
                        sale.status,
                        sale.quarantine_reason,
                        fetched_at,
                    )
                    for sale in rows
                ],
            )
        return self._count() - before

    def apply_rate(
        self, sale_id: int, price_twd: int, rate: float, rate_date: str, source: str
    ) -> None:
        """換算結果與它實際採用的匯率、日期、來源一起寫入，可事後稽核。"""
        with self._connection:
            self._connection.execute(
                "UPDATE sale SET price_twd = ?, fx_rate = ?, fx_rate_date = ?, "
                "fx_source = ?, status = ?, quarantine_reason = NULL WHERE id = ?",
                (price_twd, rate, rate_date, source, STATUS_ACTIVE, sale_id),
            )

    def quarantine(self, sale_id: int, reason: str) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE sale SET status = ?, quarantine_reason = ?, price_twd = NULL, "
                "fx_rate = NULL, fx_rate_date = NULL, fx_source = NULL WHERE id = ?",
                (STATUS_QUARANTINED, reason, sale_id),
            )

    def awaiting_rate(self) -> tuple[dict, ...]:
        """尚未換算的成交：剛寫入的，以及先前因抓不到匯率而待審的。

        後者在下一輪爬取會自動再試一次——臺銀的機器人保護是間歇性的，把一次被擋
        變成永久待審，等於讓暫時性的故障看起來像資料問題。
        """
        placeholders = ", ".join("?" * len(RETRYABLE_FX_REASONS))
        rows = self._connection.execute(
            f"{_SELECT_SALE} WHERE sale.price_twd IS NULL "
            f"AND (sale.status = ? OR sale.quarantine_reason IN ({placeholders})) "
            "ORDER BY sale.id",
            (STATUS_ACTIVE, *RETRYABLE_FX_REASONS),
        )
        return tuple(dict(row) for row in rows)

    def active_for_apparel(self, apparel_id: int) -> tuple[dict, ...]:
        rows = self._connection.execute(
            f"{_SELECT_SALE} WHERE sale.apparel_id = ? AND sale.status = ? "
            "AND sale.price_twd IS NOT NULL ORDER BY sale.sold_date_jst, sale.id",
            (apparel_id, STATUS_ACTIVE),
        )
        return tuple(dict(row) for row in rows)

    def active_by_apparel(self) -> dict[int, list[dict]]:
        rows = self._connection.execute(
            f"{_SELECT_SALE} WHERE sale.status = ? AND sale.price_twd IS NOT NULL "
            "ORDER BY sale.sold_date_jst, sale.id",
            (STATUS_ACTIVE,),
        )
        grouped: dict[int, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["apparel_id"], []).append(dict(row))
        return grouped

    def list_for_apparel(self, apparel_id: int) -> tuple[dict, ...]:
        rows = self._connection.execute(
            f"{_SELECT_SALE} WHERE sale.apparel_id = ? "
            "ORDER BY sale.sold_date_jst DESC, sale.id",
            (apparel_id,),
        )
        return tuple(dict(row) for row in rows)

    def list_quarantined(self) -> tuple[dict, ...]:
        """待審清單一律帶著卡種名——只有 apparel id 的清單看不出擋下了什麼。"""
        rows = self._connection.execute(
            f"""
            SELECT {_SALE_COLUMNS},
                   card.series_raw,
                   card.number_raw,
                   card.card_name_raw
            FROM sale
            JOIN card ON card.apparel_id = sale.apparel_id
            WHERE sale.status = ?
            ORDER BY sale.sold_date_jst DESC, sale.id
            """,
            (STATUS_QUARANTINED,),
        )
        return tuple(dict(row) for row in rows)

    def quarantined_counts(self) -> dict[int, int]:
        rows = self._connection.execute(
            "SELECT apparel_id, COUNT(*) AS total FROM sale WHERE status = ? "
            "GROUP BY apparel_id",
            (STATUS_QUARANTINED,),
        )
        return {row["apparel_id"]: row["total"] for row in rows}

    def _count(self) -> int:
        return self._connection.execute(
            "SELECT COUNT(*) AS total FROM sale"
        ).fetchone()["total"]
