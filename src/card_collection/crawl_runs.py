"""爬取帳本：每一輪跑了什麼、結果如何。

爬取改成自動之後，系統必須自己記得住上次何時跑、出了什麼事——否則來源改版或被擋
時，畫面只會靜靜停在三週前（共識書 C6：安靜說謊的儀表板比沒有儀表板更糟）。

帳本同時是**鎖**：`crawl_run (status) WHERE status = 'running'` 的 partial unique
index 讓同時只有一輪跑得起來。鎖必須能自己解開——行程被砍或當機時，`running`
那一列不會有人去收拾，少了自解，一次當機就讓爬取永遠啟動不了。
"""

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULED = "scheduled"

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

# 一輪實測約 1.7 分鐘。掛著 running 超過 30 分鐘的不是慢，是死了。
STALE_LOCK_MINUTES = 30
ABANDONED_ERROR = "上一輪超過 30 分鐘未結束，判定為執行它的行程已死"

# 超過這麼久沒有成功爬取，畫面就得出聲。一天一輪，容許一輪的誤差。
STALE_AFTER_HOURS = 24


class CrawlRunInProgress(Exception):
    """已經有一輪在跑。帶著那一輪的 id，好讓呼叫端說得出是哪一輪。"""

    def __init__(self, run_id: int) -> None:
        super().__init__(f"已有一輪爬取正在進行（run {run_id}）")
        self.run_id = run_id


@dataclass(frozen=True)
class CrawlOutcome:
    """一輪爬取的統計。帳本只認這個形狀，不認 `crawl()` 那份報告的全貌。"""

    card_count: int
    fetched: int
    inserted: int
    quarantined: int
    skipped_count: int
    fx_converted: int
    fx_error: str | None
    failures: tuple[dict, ...]

    @classmethod
    def from_report(cls, report: dict) -> "CrawlOutcome":
        """報告 → 帳本的欄位對應只能有一個地方說了算。"""
        totals = report["totals"]
        return cls(
            card_count=totals["cards"],
            fetched=totals["fetched"],
            inserted=totals["inserted"],
            quarantined=totals["quarantined"],
            skipped_count=totals["skipped"],
            fx_converted=report["fx"]["converted"],
            fx_error=report["fx"]["error"],
            failures=tuple(report["failed"]),
        )


class CrawlRunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def start(self, trigger: str, now: datetime) -> int:
        """開一輪。已經有一輪在跑就丟 `CrawlRunInProgress`，一個請求都不送出。"""
        self._release_stale_lock(now)
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "INSERT INTO crawl_run (trigger, status, started_at)"
                    " VALUES (?, ?, ?)",
                    (trigger, STATUS_RUNNING, now.isoformat()),
                )
        except sqlite3.IntegrityError as error:
            running = self.running()
            raise CrawlRunInProgress(running["id"] if running else 0) from error
        return int(cursor.lastrowid)

    def finish(self, run_id: int, outcome: CrawlOutcome, now: datetime) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE crawl_run
                   SET status = ?, finished_at = ?, card_count = ?, fetched = ?,
                       inserted = ?, quarantined = ?, skipped_count = ?,
                       fx_converted = ?, fx_error = ?, failures = ?
                 WHERE id = ?
                """,
                (
                    STATUS_SUCCEEDED,
                    now.isoformat(),
                    outcome.card_count,
                    outcome.fetched,
                    outcome.inserted,
                    outcome.quarantined,
                    outcome.skipped_count,
                    outcome.fx_converted,
                    outcome.fx_error,
                    json.dumps(outcome.failures, ensure_ascii=False),
                    run_id,
                ),
            )

    def fail(self, run_id: int, error: str, now: datetime) -> None:
        """整輪炸掉。原因一定要落地，否則那一列會永遠停在 running 冒充「在跑」。"""
        with self._connection:
            self._connection.execute(
                "UPDATE crawl_run SET status = ?, finished_at = ?, error = ?"
                " WHERE id = ?",
                (STATUS_FAILED, now.isoformat(), error, run_id),
            )

    def running(self) -> dict | None:
        return self._one(
            "SELECT * FROM crawl_run WHERE status = ? ORDER BY id DESC LIMIT 1",
            (STATUS_RUNNING,),
        )

    def latest(self) -> dict | None:
        """最近一輪，不論成敗。畫面要靠它顯示上一輪的失敗與匯率錯誤。"""
        return self._one("SELECT * FROM crawl_run ORDER BY id DESC LIMIT 1", ())

    def last_succeeded(self) -> dict | None:
        """最近一輪**成功**的。過期與否只能由它決定——失敗的那輪不算更新過。"""
        return self._one(
            "SELECT * FROM crawl_run WHERE status = ? ORDER BY id DESC LIMIT 1",
            (STATUS_SUCCEEDED,),
        )

    def list_recent(self, limit: int = 20) -> tuple[dict, ...]:
        rows = self._connection.execute(
            "SELECT * FROM crawl_run ORDER BY id DESC LIMIT ?", (limit,)
        )
        return tuple(_to_dict(row) for row in rows)

    def _release_stale_lock(self, now: datetime) -> None:
        """卡死的鎖自己解開，並標明它是被判定死亡，不是一次真正的爬取失敗。"""
        running = self.running()
        if running is None:
            return
        started = datetime.fromisoformat(running["started_at"])
        if now - started <= timedelta(minutes=STALE_LOCK_MINUTES):
            return
        self.fail(running["id"], ABANDONED_ERROR, now)

    def _one(self, sql: str, parameters: Iterable) -> dict | None:
        row = self._connection.execute(sql, tuple(parameters)).fetchone()
        return None if row is None else _to_dict(row)


def _to_dict(row: sqlite3.Row) -> dict:
    """`failures` 進出都是 JSON 字串，呼叫端拿到的一律是解好的清單。"""
    record = dict(row)
    record["failures"] = json.loads(record["failures"] or "[]")
    return record


def freshness(
    latest: dict | None,
    last_success: dict | None,
    now: datetime,
    stale_after_hours: int = STALE_AFTER_HOURS,
) -> dict:
    """畫面要的那句「上次更新多久以前」，以及該不該出示過期警示。

    **從未成功過**與**成功過但太久以前**都算過期。前者若不算，第一次就壞掉的
    情況會被當成正常——那正是這一層要防的。
    """
    age_hours = None
    if last_success is not None and last_success["finished_at"]:
        finished = datetime.fromisoformat(last_success["finished_at"])
        age_hours = (now - finished).total_seconds() / 3600
    return {
        "latest": latest,
        "last_success": last_success,
        "age_hours": age_hours,
        "age_label": _age_label(age_hours),
        "never_succeeded": last_success is None,
        "is_stale": age_hours is None or age_hours > stale_after_hours,
    }


def _age_label(age_hours: float | None) -> str | None:
    """給人看的「多久以前」。小數點後的小時數對這個判斷沒有任何幫助。"""
    if age_hours is None:
        return None
    if age_hours < 1:
        return "不到 1 小時"
    if age_hours < 48:
        return f"{int(age_hours)} 小時"
    return f"{int(age_hours // 24)} 天"
