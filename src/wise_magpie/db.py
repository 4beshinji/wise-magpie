"""SQLite persistence layer."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from wise_magpie import config, constants
from wise_magpie.models import (
    ActivitySession,
    QuotaWindow,
    SchedulePattern,
    Task,
    TaskSource,
    TaskStatus,
    UsageRecord,
)

SCHEMA = """\
CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    task_id INTEGER,
    autonomous INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quota_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_start TEXT NOT NULL,
    window_hours INTEGER NOT NULL DEFAULT 5,
    estimated_limit INTEGER NOT NULL DEFAULT 225,
    used_count INTEGER NOT NULL DEFAULT 0,
    user_correction INTEGER,
    corrected_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    source_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    priority REAL NOT NULL DEFAULT 0.0,
    model TEXT NOT NULL DEFAULT '',
    estimated_tokens INTEGER NOT NULL DEFAULT 0,
    work_branch TEXT NOT NULL DEFAULT '',
    work_dir TEXT NOT NULL DEFAULT '',
    result_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS quota_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    remaining INTEGER NOT NULL,
    corrected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_patterns (
    day_of_week INTEGER NOT NULL,
    hour INTEGER NOT NULL,
    activity_probability REAL NOT NULL DEFAULT 0.0,
    avg_usage REAL NOT NULL DEFAULT 0.0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day_of_week, hour)
);

CREATE TABLE IF NOT EXISTS activity_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_activity_start ON activity_sessions(start_time);
"""


def _db_path() -> Path:
    return config.data_dir() / constants.DB_FILE_NAME


def _parse_dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _fmt_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections."""
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize the database schema and run migrations."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Run schema migrations for columns added after initial release."""
    # Add model column to tasks if missing
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "model" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN model TEXT NOT NULL DEFAULT ''")


# --- Usage Log ---

def insert_usage(record: UsageRecord) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO usage_log (timestamp, model, input_tokens, output_tokens, cost_usd, task_id, autonomous) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_fmt_dt(record.timestamp), record.model, record.input_tokens,
             record.output_tokens, record.cost_usd, record.task_id, int(record.autonomous)),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_usage_since(since: datetime) -> list[UsageRecord]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM usage_log WHERE timestamp >= ? ORDER BY timestamp",
            (_fmt_dt(since),),
        ).fetchall()
    return [
        UsageRecord(
            id=r["id"], timestamp=_parse_dt(r["timestamp"]),  # type: ignore[arg-type]
            model=r["model"], input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"], cost_usd=r["cost_usd"],
            task_id=r["task_id"], autonomous=bool(r["autonomous"]),
        )
        for r in rows
    ]


def get_daily_autonomous_cost(date: datetime) -> float:
    """Get total autonomous cost for a given date."""
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) as total FROM usage_log "
            "WHERE autonomous = 1 AND timestamp BETWEEN ? AND ?",
            (_fmt_dt(day_start), _fmt_dt(day_end)),
        ).fetchone()
    return row["total"]


# --- Quota Windows ---

def insert_quota_window(window: QuotaWindow) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO quota_windows (window_start, window_hours, estimated_limit, used_count, user_correction, corrected_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_fmt_dt(window.window_start), window.window_hours, window.estimated_limit,
             window.used_count, window.user_correction, _fmt_dt(window.corrected_at)),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_current_quota_window() -> QuotaWindow | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM quota_windows ORDER BY window_start DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return QuotaWindow(
        id=row["id"], window_start=_parse_dt(row["window_start"]),  # type: ignore[arg-type]
        window_hours=row["window_hours"], estimated_limit=row["estimated_limit"],
        used_count=row["used_count"], user_correction=row["user_correction"],
        corrected_at=_parse_dt(row["corrected_at"]),
    )


def update_quota_window(window: QuotaWindow) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE quota_windows SET used_count=?, user_correction=?, corrected_at=? WHERE id=?",
            (window.used_count, window.user_correction, _fmt_dt(window.corrected_at), window.id),
        )


# --- Tasks ---

def insert_task(task: Task) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, description, source, source_ref, status, priority, model, "
            "estimated_tokens, work_branch, work_dir, result_summary, created_at, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task.title, task.description, task.source.value, task.source_ref,
             task.status.value, task.priority, task.model, task.estimated_tokens,
             task.work_branch, task.work_dir, task.result_summary,
             _fmt_dt(task.created_at), _fmt_dt(task.started_at), _fmt_dt(task.completed_at)),
        )
        return cur.lastrowid  # type: ignore[return-value]


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"], title=row["title"], description=row["description"],
        source=TaskSource(row["source"]), source_ref=row["source_ref"],
        status=TaskStatus(row["status"]), priority=row["priority"],
        model=row["model"],
        estimated_tokens=row["estimated_tokens"],
        work_branch=row["work_branch"], work_dir=row["work_dir"],
        result_summary=row["result_summary"],
        created_at=_parse_dt(row["created_at"]),  # type: ignore[arg-type]
        started_at=_parse_dt(row["started_at"]),
        completed_at=_parse_dt(row["completed_at"]),
    )


def get_task(task_id: int) -> Task | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def get_tasks_by_status(*statuses: TaskStatus) -> list[Task]:
    placeholders = ",".join("?" for _ in statuses)
    values = [s.value for s in statuses]
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY priority DESC, created_at",
            values,
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def get_all_tasks() -> list[Task]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    return [_row_to_task(r) for r in rows]


def update_task(task: Task) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE tasks SET title=?, description=?, source=?, source_ref=?, status=?, "
            "priority=?, model=?, estimated_tokens=?, work_branch=?, work_dir=?, result_summary=?, "
            "started_at=?, completed_at=? WHERE id=?",
            (task.title, task.description, task.source.value, task.source_ref,
             task.status.value, task.priority, task.model, task.estimated_tokens,
             task.work_branch, task.work_dir, task.result_summary,
             _fmt_dt(task.started_at), _fmt_dt(task.completed_at), task.id),
        )


def delete_task(task_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        return cur.rowcount > 0


# --- Schedule Patterns ---

def upsert_schedule_pattern(pattern: SchedulePattern) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO schedule_patterns (day_of_week, hour, activity_probability, avg_usage, sample_count) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(day_of_week, hour) DO UPDATE SET "
            "activity_probability=excluded.activity_probability, "
            "avg_usage=excluded.avg_usage, sample_count=excluded.sample_count",
            (pattern.day_of_week, pattern.hour, pattern.activity_probability,
             pattern.avg_usage, pattern.sample_count),
        )


def get_schedule_patterns() -> list[SchedulePattern]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_patterns ORDER BY day_of_week, hour"
        ).fetchall()
    return [
        SchedulePattern(
            day_of_week=r["day_of_week"], hour=r["hour"],
            activity_probability=r["activity_probability"],
            avg_usage=r["avg_usage"], sample_count=r["sample_count"],
        )
        for r in rows
    ]


# --- Activity Sessions ---

def insert_activity_session(session: ActivitySession) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO activity_sessions (start_time, end_time, message_count) VALUES (?, ?, ?)",
            (_fmt_dt(session.start_time), _fmt_dt(session.end_time), session.message_count),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_recent_sessions(limit: int = 50) -> list[ActivitySession]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_sessions ORDER BY start_time DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        ActivitySession(
            id=r["id"], start_time=_parse_dt(r["start_time"]),  # type: ignore[arg-type]
            end_time=_parse_dt(r["end_time"]), message_count=r["message_count"],
        )
        for r in rows
    ]


def update_activity_session(session: ActivitySession) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE activity_sessions SET end_time=?, message_count=? WHERE id=?",
            (_fmt_dt(session.end_time), session.message_count, session.id),
        )


# --- Model Usage ---

def get_model_usage_count(model: str, since: datetime) -> int:
    """Return the number of usage_log records for *model* since *since*."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM usage_log WHERE model = ? AND timestamp >= ?",
            (model, _fmt_dt(since)),
        ).fetchone()
    return row["cnt"]


# --- Quota Corrections ---

def insert_quota_correction(window_id: int, model: str, remaining: int) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO quota_corrections (window_id, model, remaining, corrected_at) "
            "VALUES (?, ?, ?, ?)",
            (window_id, model, remaining, _fmt_dt(datetime.now())),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_latest_quota_correction(window_id: int, model: str) -> dict | None:
    """Return the most recent correction for *model* in *window_id*, or None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM quota_corrections "
            "WHERE window_id = ? AND model = ? ORDER BY corrected_at DESC LIMIT 1",
            (window_id, model),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "window_id": row["window_id"],
        "model": row["model"],
        "remaining": row["remaining"],
        "corrected_at": _parse_dt(row["corrected_at"]),
    }
