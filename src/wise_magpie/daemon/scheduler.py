"""Execution decision logic - determines when to run autonomous tasks."""

from __future__ import annotations

import math
from datetime import datetime

from wise_magpie import config, constants, db
from wise_magpie.models import TaskStatus
from wise_magpie.worker.monitor import check_budget_available


def calculate_max_parallel(
    remaining_pct: float,
    hours_until_reset: float,
    *,
    cap: int = constants.MAX_PARALLEL_TASKS,
) -> int:
    """Compute the maximum number of parallel tasks allowed.

    Uses a geometric mean of quota remaining and time until the quota window
    resets.  Either factor reaching zero collapses parallelism to 1.

    Args:
        remaining_pct: Quota remaining as a percentage (0-100).
        hours_until_reset: Hours until the 5-hour quota window resets (0-5).
        cap: Hard upper bound (default: MAX_PARALLEL_TASKS).

    Returns:
        An integer in [1, cap].
    """
    quota_ratio = max(remaining_pct, 0.0) / 100.0
    time_ratio = min(max(hours_until_reset, 0.0) / constants.DEFAULT_QUOTA_WINDOW_HOURS, 1.0)

    # Geometric mean: quota=0 or time=0 → sequential only.
    score = math.sqrt(quota_ratio * time_ratio)

    if score >= 0.75:
        n = 4
    elif score >= 0.50:
        n = 3
    elif score >= 0.25:
        n = 2
    else:
        n = 1

    return min(n, max(cap, 1))


def get_parallel_limit() -> int:
    """Return the current parallel task limit.

    Takes the minimum of two independent limits:
    - **5-hour window limit**: based on remaining quota and time until the
      current 5-hour window resets (``calculate_max_parallel``).
    - **Weekly budget limit**: computed every 30 minutes from the weekly
      usage percentage, ensuring wise-magpie lands at ≤ 90% at weekly reset.
    """
    cfg = config.load_config()
    cap = cfg.get("daemon", {}).get("max_parallel_tasks", constants.MAX_PARALLEL_TASKS)

    # 5-hour window limit
    try:
        from wise_magpie.quota.estimator import estimate_remaining

        est = estimate_remaining()
        remaining_pct = est["remaining_pct"]
        window_end: datetime = est["window_end"]
        hours_until_reset = max((window_end - datetime.now()).total_seconds() / 3600, 0.0)
        window_limit = calculate_max_parallel(remaining_pct, hours_until_reset, cap=cap)
    except Exception:
        window_limit = 1  # Safe fallback

    # Weekly budget limit (updated every 30 min by the daemon)
    try:
        from wise_magpie.quota.weekly_budget import get_weekly_parallel_limit

        weekly_limit = get_weekly_parallel_limit()
    except Exception:
        weekly_limit = cap

    return min(window_limit, weekly_limit)


def should_execute() -> tuple[bool, str]:
    """Determine if the daemon should start a new autonomous task.

    Execution is gated only on quota/budget availability and parallel slot
    capacity.  User activity is no longer a blocker: tasks run in parallel
    with the user as long as quota remains.

    Returns (should_run, reason).
    """
    db.init_db()

    # Check 1: Is there budget?
    has_budget, budget_reason = check_budget_available()
    if not has_budget:
        return False, budget_reason

    # Check 2: Are there pending tasks?
    pending = db.get_tasks_by_status(TaskStatus.PENDING)
    if not pending:
        return False, "No pending tasks in queue"

    # Check 3: Is a parallel slot available?
    running = db.get_tasks_by_status(TaskStatus.RUNNING)
    max_parallel = get_parallel_limit()
    if len(running) >= max_parallel:
        return False, f"{len(running)} tasks running (parallel limit: {max_parallel})"

    return (
        True,
        f"{len(pending)} pending tasks, budget available"
        f" (parallel: {len(running)+1}/{max_parallel})",
    )
