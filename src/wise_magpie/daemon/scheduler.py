"""Execution decision logic - determines when to run autonomous tasks."""

from __future__ import annotations

from datetime import datetime, timedelta

import click

from wise_magpie import config, constants, db
from wise_magpie.models import TaskStatus
from wise_magpie.patterns.activity import get_idle_minutes, is_user_active
from wise_magpie.patterns.predictor import predict_next_return
from wise_magpie.worker.monitor import check_budget_available


def should_execute() -> tuple[bool, str]:
    """Determine if the daemon should start a new autonomous task.

    Uses triple-check: activity detection + idle timer + schedule prediction.
    Returns (should_run, reason).
    """
    db.init_db()
    cfg = config.load_config()

    # Check 1: Is user currently active?
    if is_user_active():
        return False, "User is currently active (Claude process detected)"

    # Check 2: Has user been idle long enough?
    idle_threshold = cfg.get("activity", {}).get(
        "idle_threshold_minutes", constants.IDLE_THRESHOLD_MINUTES
    )
    idle_mins = get_idle_minutes()
    if idle_mins < idle_threshold:
        return False, f"User idle only {idle_mins:.0f}m (threshold: {idle_threshold}m)"

    # Check 3: Is user expected to return soon?
    return_buffer = cfg.get("activity", {}).get(
        "return_buffer_minutes", constants.RETURN_BUFFER_MINUTES
    )
    next_return = predict_next_return()
    if next_return is not None:
        time_until_return = (next_return - datetime.now()).total_seconds() / 60
        if time_until_return < return_buffer:
            return False, (
                f"User predicted to return in {time_until_return:.0f}m "
                f"(buffer: {return_buffer}m)"
            )

    # Check 4: Is there budget?
    has_budget, budget_reason = check_budget_available()
    if not has_budget:
        return False, budget_reason

    # Check 5: Are there pending tasks?
    pending = db.get_tasks_by_status(TaskStatus.PENDING)
    if not pending:
        return False, "No pending tasks in queue"

    # Check 6: Is another task already running?
    running = db.get_tasks_by_status(TaskStatus.RUNNING)
    if running:
        return False, f"Task #{running[0].id} is already running"

    return True, f"Idle {idle_mins:.0f}m, {len(pending)} pending tasks, budget available"
