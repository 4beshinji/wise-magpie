"""Manual quota corrections from the Claude UI remaining count."""

from __future__ import annotations

from datetime import datetime, timedelta

import click

from wise_magpie import config, constants, db
from wise_magpie.models import QuotaWindow


def apply_correction(remaining_count: int) -> None:
    """Record a user-supplied remaining message count.

    Updates the current quota window's *user_correction* and
    *corrected_at* fields.  If no window exists yet, one is created
    first.
    """
    db.init_db()

    window = db.get_current_quota_window()
    if window is None:
        window_hours = config.get("quota", "window_hours", constants.DEFAULT_QUOTA_WINDOW_HOURS)
        messages = config.get("quota", "messages_per_window", constants.DEFAULT_MESSAGES_PER_WINDOW)
        window = QuotaWindow(
            window_start=datetime.now(),
            window_hours=window_hours,
            estimated_limit=messages,
            used_count=0,
        )
        window.id = db.insert_quota_window(window)

    window.user_correction = remaining_count
    window.corrected_at = datetime.now()
    db.update_quota_window(window)

    used = window.estimated_limit - remaining_count
    click.echo(f"Correction applied: {remaining_count} messages remaining "
               f"(~{used} used of {window.estimated_limit}).")
