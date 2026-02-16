"""Manual quota corrections from the Claude UI remaining count."""

from __future__ import annotations

from datetime import datetime, timedelta

import click

from wise_magpie import config, constants, db
from wise_magpie.constants import resolve_model
from wise_magpie.models import QuotaWindow
from wise_magpie.quota.estimator import get_model_limit


def apply_correction(remaining_count: int, model: str | None = None) -> None:
    """Record a user-supplied remaining message count.

    If *model* is specified, records a per-model correction in the
    ``quota_corrections`` table.  Otherwise falls back to the legacy
    per-window ``user_correction`` field for backward compatibility.
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

    if model:
        resolved = resolve_model(model)
        model_limit = get_model_limit(resolved)
        db.insert_quota_correction(window.id, resolved, remaining_count)  # type: ignore[arg-type]
        used = model_limit - remaining_count
        click.echo(
            f"Correction applied for {model}: {remaining_count} messages remaining "
            f"(~{used} used of {model_limit})."
        )
    else:
        # Legacy: update per-window correction
        window.user_correction = remaining_count
        window.corrected_at = datetime.now()
        db.update_quota_window(window)

        used = window.estimated_limit - remaining_count
        click.echo(f"Correction applied: {remaining_count} messages remaining "
                   f"(~{used} used of {window.estimated_limit}).")
