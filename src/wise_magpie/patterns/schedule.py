"""Schedule pattern learning for wise-magpie.

Analyzes historical activity sessions to build a per-day-of-week, per-hour
probability model of when the user is typically active.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import click

from wise_magpie import db, config, constants
from wise_magpie.models import SchedulePattern


def update_patterns() -> None:
    """Rebuild schedule patterns from stored activity sessions.

    For every (day_of_week, hour) combination, compute:
    * ``activity_probability`` -- fraction of sampled hours where the user was
      active.
    * ``avg_usage`` -- average message count during active hours.

    Results are upserted into the ``schedule_patterns`` table.
    """
    db.init_db()
    sessions = db.get_recent_sessions(limit=5000)

    if not sessions:
        return

    # Collect per-slot stats.
    # active_counts[day][hour]  = number of hours where user was active
    # total_counts[day][hour]   = number of hours we have data for
    # usage_totals[day][hour]   = sum of message_count contributions
    active_counts: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    total_counts: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    usage_totals: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))

    # Determine the date range covered by sessions so we know which
    # (day, hour) slots have been observed.
    earliest = min(s.start_time for s in sessions)
    latest_end = max(
        (s.end_time if s.end_time is not None else s.start_time) for s in sessions
    )

    # Walk each calendar hour from earliest to latest and mark observed slots.
    cursor = earliest.replace(minute=0, second=0, microsecond=0)
    while cursor <= latest_end:
        dow = cursor.weekday()  # 0=Monday
        h = cursor.hour
        total_counts[dow][h] += 1
        cursor += timedelta(hours=1)

    # For each session, mark every hour it spans as active.
    for session in sessions:
        start = session.start_time
        end = session.end_time if session.end_time is not None else start
        # Walk hours covered by this session.
        hour_cursor = start.replace(minute=0, second=0, microsecond=0)
        while hour_cursor <= end:
            dow = hour_cursor.weekday()
            h = hour_cursor.hour
            active_counts[dow][h] += 1
            # Distribute message_count evenly across session hours.
            session_hours = max(
                (end - start).total_seconds() / 3600.0, 1.0
            )
            usage_totals[dow][h] += session.message_count / session_hours
            hour_cursor += timedelta(hours=1)

    # Upsert patterns.
    for dow in range(7):
        for h in range(24):
            total = total_counts[dow][h]
            if total == 0:
                continue
            active = active_counts[dow][h]
            probability = min(active / total, 1.0)
            avg_usage = usage_totals[dow][h] / total if total else 0.0

            pattern = SchedulePattern(
                day_of_week=dow,
                hour=h,
                activity_probability=probability,
                avg_usage=avg_usage,
                sample_count=total,
            )
            db.upsert_schedule_pattern(pattern)


def get_pattern(day_of_week: int, hour: int) -> SchedulePattern | None:
    """Return the schedule pattern for a specific (day_of_week, hour) slot.

    Returns ``None`` if no pattern has been recorded for that slot.
    """
    db.init_db()
    patterns = db.get_schedule_patterns()
    for p in patterns:
        if p.day_of_week == day_of_week and p.hour == hour:
            return p
    return None


def show_patterns() -> None:
    """Display a 7x24 grid of activity patterns in the terminal.

    Rows are days of the week (Mon-Sun), columns are hours (0-23).
    Visual indicators by probability:
        ``\u00b7``  no data
        ``\u2591``  < 0.25
        ``\u2592``  < 0.50
        ``\u2593``  < 0.75
        ``\u2588``  >= 0.75
    """
    db.init_db()
    patterns = db.get_schedule_patterns()

    # Build a lookup: (day_of_week, hour) -> SchedulePattern
    lookup: dict[tuple[int, int], SchedulePattern] = {}
    for p in patterns:
        lookup[(p.day_of_week, p.hour)] = p

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # Header row.
    header = "     " + "".join(f"{h:>3}" for h in range(24))
    click.echo(header)

    for dow, name in enumerate(day_names):
        row_chars: list[str] = []
        for h in range(24):
            p = lookup.get((dow, h))
            if p is None or p.sample_count == 0:
                row_chars.append("  \u00b7")
            elif p.activity_probability < 0.25:
                row_chars.append("  \u2591")
            elif p.activity_probability < 0.50:
                row_chars.append("  \u2592")
            elif p.activity_probability < 0.75:
                row_chars.append("  \u2593")
            else:
                row_chars.append("  \u2588")
        click.echo(f"{name:>4} " + "".join(row_chars))

    # Legend.
    click.echo()
    click.echo("Legend: \u00b7 no data  \u2591 <25%  \u2592 <50%  \u2593 <75%  \u2588 >=75%")
