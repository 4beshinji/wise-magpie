"""Weekly quota budget: compute max parallel tasks from weekly consumption rate.

Every 30 minutes the daemon calls ``update_weekly_limit()``, which:

1. Fetches the current weekly usage percentage from the Anthropic API.
2. Estimates the consumption rate by comparing to the previous measurement
   and normalising by the number of tasks that were running at that time.
3. Solves for the maximum parallel-task count ``n`` such that:

       week_pct + rate_per_task × n × hours_until_reset ≤ WEEKLY_QUOTA_TARGET_PCT

   i.e. if wise-magpie runs at ``n`` parallelism continuously until the
   weekly quota resets, it lands at exactly the target percentage.

The computed limit is cached in a module-level variable and consumed by
``get_parallel_limit()`` in scheduler.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from wise_magpie import config, constants, db
from wise_magpie.models import TaskStatus
from wise_magpie.quota.claude_api import fetch_usage

logger = logging.getLogger("wise-magpie")

# ---------------------------------------------------------------------------
# Module-level state (updated every 30 minutes by the daemon loop)
# ---------------------------------------------------------------------------

_last_week_pct: float | None = None
_last_checked_at: datetime | None = None
_last_n_running: int = 1
_weekly_parallel_limit: int = constants.MAX_PARALLEL_TASKS


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def get_hours_until_weekly_reset() -> float:
    """Return hours until the weekly quota window resets (UTC).

    Reads ``quota.weekly_reset_day`` (0=Mon … 6=Sun, default 0) and
    ``quota.weekly_reset_hour`` (UTC integer, default 0) from config.
    """
    cfg = config.load_config()
    reset_day: int = cfg.get("quota", {}).get("weekly_reset_day", constants.WEEKLY_RESET_DAY)
    reset_hour: int = cfg.get("quota", {}).get("weekly_reset_hour", constants.WEEKLY_RESET_HOUR)

    now = datetime.now(timezone.utc)
    days_ahead = reset_day - now.weekday()
    if days_ahead < 0:
        days_ahead += 7
    elif days_ahead == 0 and now.hour >= reset_hour:
        days_ahead = 7

    next_reset = (now + timedelta(days=days_ahead)).replace(
        hour=reset_hour, minute=0, second=0, microsecond=0
    )
    return max((next_reset - now).total_seconds() / 3600, 0.0)


def compute_weekly_parallel_limit(
    week_pct: float,
    rate_pct_per_hour: float,
    hours_until_reset: float,
    n_running: int,
    *,
    target_pct: float = constants.WEEKLY_QUOTA_TARGET_PCT,
    cap: int = constants.MAX_PARALLEL_TASKS,
) -> int:
    """Solve for the max parallel count that keeps weekly usage ≤ *target_pct*.

    Finds the largest integer ``n`` satisfying:

        week_pct + (rate_pct_per_hour / n_running) × n × hours_until_reset ≤ target_pct

    where ``rate_pct_per_hour / n_running`` is the estimated per-task rate.

    Args:
        week_pct: Current weekly usage percentage (0-100).
        rate_pct_per_hour: Total observed rate of weekly-% consumed per hour.
        hours_until_reset: Hours until the weekly quota window resets.
        n_running: Average number of tasks observed during the rate window
            (used to normalise the rate to a per-task value).
        target_pct: Maximum acceptable weekly usage at reset time (default 90%).
        cap: Hard upper bound on the returned value.

    Returns:
        An integer in [1, cap].
    """
    remaining = target_pct - week_pct
    if remaining <= 0:
        return 1
    if rate_pct_per_hour <= 0 or hours_until_reset <= 0:
        return cap

    rate_per_task = rate_pct_per_hour / max(n_running, 1)
    n = remaining / (rate_per_task * hours_until_reset)
    return max(1, min(int(n), cap))


# ---------------------------------------------------------------------------
# Stateful updater (called by daemon every 30 minutes)
# ---------------------------------------------------------------------------


def update_weekly_limit() -> int:
    """Fetch current weekly usage and recompute the parallel task ceiling.

    Updates the module-level ``_weekly_parallel_limit`` and returns the new
    value.  On any failure the previous limit is preserved.
    """
    global _last_week_pct, _last_checked_at, _last_n_running, _weekly_parallel_limit

    cfg = config.load_config()
    cap: int = cfg.get("daemon", {}).get("max_parallel_tasks", constants.MAX_PARALLEL_TASKS)
    target_pct: float = cfg.get("quota", {}).get(
        "weekly_target_pct", constants.WEEKLY_QUOTA_TARGET_PCT
    )

    # Fetch live usage from the Anthropic API
    try:
        snapshot = fetch_usage()
    except Exception:
        logger.debug("weekly_budget: could not fetch usage snapshot", exc_info=True)
        return _weekly_parallel_limit

    if snapshot is None:
        return _weekly_parallel_limit

    week_pct: float | None = snapshot.get("week_all_pct")
    if week_pct is None:
        return _weekly_parallel_limit

    now = datetime.now(timezone.utc)
    hours_until_reset = get_hours_until_weekly_reset()

    # Estimate rate and normalised per-task rate from consecutive measurements
    rate_per_hour: float | None = None
    n_running_for_rate = _last_n_running

    if _last_week_pct is not None and _last_checked_at is not None:
        delta_pct = week_pct - _last_week_pct
        delta_hours = (now - _last_checked_at).total_seconds() / 3600
        if delta_hours > 0 and delta_pct > 0:
            rate_per_hour = delta_pct / delta_hours

    # Snapshot current running-task count for next measurement's normalisation
    try:
        running = db.get_tasks_by_status(TaskStatus.RUNNING)
        _last_n_running = max(len(running), 1)
    except Exception:
        _last_n_running = 1

    # Persist readings for next call
    _last_week_pct = week_pct
    _last_checked_at = now

    if rate_per_hour is None or rate_per_hour <= 0:
        # No usable rate yet (first call, week just reset, or no activity)
        _weekly_parallel_limit = cap
    else:
        _weekly_parallel_limit = compute_weekly_parallel_limit(
            week_pct=week_pct,
            rate_pct_per_hour=rate_per_hour,
            hours_until_reset=hours_until_reset,
            n_running=n_running_for_rate,
            target_pct=target_pct,
            cap=cap,
        )

    logger.info(
        "Weekly budget: %.1f%% used, %.0fh until reset, rate %.4f%%/h "
        "(normalised over %d tasks) → parallel limit %d (target: %.0f%%)",
        week_pct,
        hours_until_reset,
        rate_per_hour or 0.0,
        n_running_for_rate,
        _weekly_parallel_limit,
        target_pct,
    )
    return _weekly_parallel_limit


def get_weekly_parallel_limit() -> int:
    """Return the most recently computed weekly-budget parallel limit."""
    return _weekly_parallel_limit
