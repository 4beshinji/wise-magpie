"""Quota estimation: track remaining quota and budget availability."""

from __future__ import annotations

from datetime import datetime, timedelta

import click

from wise_magpie import config, constants, db
from wise_magpie.models import QuotaWindow


def _ensure_window() -> QuotaWindow:
    """Return the current quota window, creating one if none exists."""
    window = db.get_current_quota_window()
    if window is not None:
        return window

    window_hours = config.get("quota", "window_hours", constants.DEFAULT_QUOTA_WINDOW_HOURS)
    messages = config.get("quota", "messages_per_window", constants.DEFAULT_MESSAGES_PER_WINDOW)

    window = QuotaWindow(
        window_start=datetime.now(),
        window_hours=window_hours,
        estimated_limit=messages,
        used_count=0,
    )
    window.id = db.insert_quota_window(window)
    return window


def estimate_remaining() -> dict:
    """Estimate remaining quota in the current window.

    Returns a dict with keys:
        window_start, window_end, estimated_limit, used, remaining,
        remaining_pct, safety_reserved, available_for_autonomous.
    """
    db.init_db()

    window = _ensure_window()

    window_end = window.window_start + timedelta(hours=window.window_hours)

    # Determine effective remaining count.  If the user has provided a
    # manual correction we trust that value (adjusted for any usage that
    # occurred *after* the correction was applied).
    if window.user_correction is not None:
        # Usage recorded after the correction moment
        post_correction_records = db.get_usage_since(window.corrected_at)  # type: ignore[arg-type]
        used_after_correction = len(post_correction_records)
        remaining = max(window.user_correction - used_after_correction, 0)
        used = window.estimated_limit - remaining
    else:
        used = window.used_count
        remaining = max(window.estimated_limit - used, 0)

    remaining_pct = (remaining / window.estimated_limit * 100) if window.estimated_limit else 0.0

    safety_margin = config.get("quota", "safety_margin", constants.QUOTA_SAFETY_MARGIN)
    safety_reserved = int(window.estimated_limit * safety_margin)
    available_for_autonomous = max(remaining - safety_reserved, 0)

    return {
        "window_start": window.window_start,
        "window_end": window_end,
        "estimated_limit": window.estimated_limit,
        "used": used,
        "remaining": remaining,
        "remaining_pct": remaining_pct,
        "safety_reserved": safety_reserved,
        "available_for_autonomous": available_for_autonomous,
    }


def show_quota() -> None:
    """Display a human-readable quota summary."""
    db.init_db()

    info = estimate_remaining()

    click.echo("Quota Status")
    click.echo("=" * 40)
    click.echo(f"Window:        {info['window_start'].strftime('%H:%M')} - {info['window_end'].strftime('%H:%M')}")
    click.echo(f"Limit:         {info['estimated_limit']} messages")
    click.echo(f"Used:          {info['used']} messages")
    click.echo(f"Remaining:     {info['remaining']} ({info['remaining_pct']:.1f}%)")
    click.echo(f"Safety margin: {info['safety_reserved']} messages reserved")
    click.echo(f"Autonomous:    {info['available_for_autonomous']} messages available")


def has_budget_for_task(estimated_cost: float) -> bool:
    """Check whether there is budget for a task of the given cost.

    Considers both the overall quota remaining and the daily autonomous
    spending limit.
    """
    db.init_db()

    info = estimate_remaining()
    if info["available_for_autonomous"] <= 0:
        return False

    max_daily = config.get("budget", "max_daily_usd", constants.MAX_DAILY_AUTONOMOUS_USD)
    daily_spent = db.get_daily_autonomous_cost(datetime.now())
    if daily_spent + estimated_cost > max_daily:
        return False

    return True
