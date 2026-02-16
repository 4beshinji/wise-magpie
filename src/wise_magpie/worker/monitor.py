"""Budget guard and timeout monitoring for task execution."""

from __future__ import annotations

from datetime import datetime

import click

from wise_magpie import config, constants, db
from wise_magpie.quota.estimator import estimate_remaining, has_budget_for_task


def check_budget_available(estimated_cost: float = 0.0) -> tuple[bool, str]:
    """Check if there's budget available for autonomous task execution.

    Returns (allowed, reason) tuple.
    """
    db.init_db()
    cfg = config.load_config()

    # Check daily autonomous limit
    daily_limit = cfg.get("budget", {}).get("max_daily_usd", constants.MAX_DAILY_AUTONOMOUS_USD)
    daily_spent = db.get_daily_autonomous_cost(datetime.now())
    if daily_spent >= daily_limit:
        return False, f"Daily autonomous limit reached: ${daily_spent:.2f} / ${daily_limit:.2f}"

    remaining_daily = daily_limit - daily_spent
    if estimated_cost > remaining_daily:
        return False, (
            f"Estimated cost ${estimated_cost:.2f} exceeds remaining daily budget "
            f"${remaining_daily:.2f}"
        )

    # Check quota-level budget
    if not has_budget_for_task(estimated_cost):
        return False, "Insufficient quota remaining (safety margin enforced)"

    return True, "Budget available"


def get_task_budget(task_estimated_cost: float = 0.0) -> float:
    """Calculate the budget to allocate for a single task.

    Returns the max budget in USD for the task.
    """
    cfg = config.load_config()
    max_task = cfg.get("budget", {}).get("max_task_usd", constants.MAX_TASK_BUDGET_USD)

    # Don't exceed daily remaining
    daily_limit = cfg.get("budget", {}).get("max_daily_usd", constants.MAX_DAILY_AUTONOMOUS_USD)
    daily_spent = db.get_daily_autonomous_cost(datetime.now())
    daily_remaining = max(0, daily_limit - daily_spent)

    return min(max_task, daily_remaining)


def report_execution(task_id: int, cost: float, tokens: int, duration: float) -> None:
    """Log a summary of task execution for monitoring."""
    click.echo(
        f"  Task #{task_id}: cost=${cost:.4f}, "
        f"tokens={tokens}, duration={duration:.1f}s"
    )
