"""Manual quota corrections from Claude's /usage percentage display.

Claude's /usage command shows three usage percentages:
  - Current session X%
  - Current week (all models) X%
  - Current week (sonnet only) X%

Users enter these percentages here; wise-magpie converts them to estimated
remaining message counts for autonomous scheduling decisions.
"""

from __future__ import annotations

from datetime import datetime

import click

from wise_magpie import config, constants, db
from wise_magpie.constants import MODEL_ALIASES, resolve_model
from wise_magpie.models import QuotaWindow
from wise_magpie.quota.estimator import get_model_limit


def _ensure_window() -> QuotaWindow:
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
    return window


def auto_sync() -> bool:
    """Fetch quota from Anthropic's API and apply as corrections automatically.

    Returns True if the sync succeeded, False if it failed (e.g. no network,
    missing credentials).  Failures are non-fatal; wise-magpie continues with
    its last known values.
    """
    from wise_magpie.quota.claude_api import fetch_usage

    snapshot = fetch_usage()
    if snapshot is None:
        return False

    apply_correction(
        session=int(snapshot["five_hour_pct"]),
        week_all=(int(snapshot["week_all_pct"]) if snapshot["week_all_pct"] is not None else None),
        week_sonnet=(
            int(snapshot["week_sonnet_pct"])
            if snapshot["week_sonnet_pct"] is not None
            else None
        ),
    )
    return True


def apply_correction(
    session: int | None = None,
    week_all: int | None = None,
    week_sonnet: int | None = None,
) -> None:
    """Record usage percentages read from Claude's /usage command.

    Args:
        session:     "Current session X%" value (0-100).
                     Used to estimate remaining messages in the current
                     5-hour rate-limit window.
        week_all:    "Current week (all models) X%" value (0-100).
                     Stored for trend display; not used for window estimation.
        week_sonnet: "Current week (sonnet only) X%" value (0-100).
                     Stored for trend display; not used for window estimation.
    """
    db.init_db()

    if session is None and week_all is None and week_sonnet is None:
        click.echo("No values provided. Use --session, --week-all, or --week-sonnet.", err=True)
        return

    window = _ensure_window()
    sonnet_id = MODEL_ALIASES["sonnet"]
    sonnet_limit = get_model_limit(sonnet_id)

    if session is not None:
        if not 0 <= session <= 100:
            click.echo("--session must be between 0 and 100.", err=True)
            return
        # Store percentage; estimator derives remaining as (1 - pct/100) * limit
        db.insert_quota_correction(window.id, sonnet_id, session, scope="session")  # type: ignore[arg-type]
        remaining = int((1 - session / 100) * sonnet_limit)
        click.echo(
            f"Session correction applied: {session}% used "
            f"→ ~{remaining} messages remaining in current window."
        )

    if week_all is not None:
        if not 0 <= week_all <= 100:
            click.echo("--week-all must be between 0 and 100.", err=True)
            return
        db.insert_quota_correction(window.id, "all", week_all, scope="week_all")  # type: ignore[arg-type]
        click.echo(f"Weekly (all models) correction applied: {week_all}% used this week.")

    if week_sonnet is not None:
        if not 0 <= week_sonnet <= 100:
            click.echo("--week-sonnet must be between 0 and 100.", err=True)
            return
        db.insert_quota_correction(window.id, sonnet_id, week_sonnet, scope="week_sonnet")  # type: ignore[arg-type]
        click.echo(f"Weekly (sonnet only) correction applied: {week_sonnet}% used this week.")
