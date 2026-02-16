"""Idle window prediction for wise-magpie.

Uses learned schedule patterns to forecast when the user will be away,
estimate wasted quota, and identify good windows for autonomous work.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import click

from wise_magpie import db, config, constants
from wise_magpie.models import SchedulePattern

# Probability threshold below which an hour is considered "idle".
_IDLE_PROBABILITY_THRESHOLD = 0.25

# Probability threshold above which an hour is considered "active".
_ACTIVE_PROBABILITY_THRESHOLD = 0.50


def _get_pattern_lookup() -> dict[tuple[int, int], SchedulePattern]:
    """Load all schedule patterns into a (day_of_week, hour) lookup."""
    patterns = db.get_schedule_patterns()
    return {(p.day_of_week, p.hour): p for p in patterns}


def predict_idle_windows(hours_ahead: int = 24) -> list[dict]:
    """Predict idle windows over the next *hours_ahead* hours.

    Returns a list of dicts, each containing:
        * ``start`` (datetime) -- predicted start of idle window
        * ``end`` (datetime) -- predicted end of idle window
        * ``duration_hours`` (float) -- length in hours
        * ``confidence`` (float) -- average (1 - activity_probability) during
          the window, or 0.5 if no pattern data exists for a slot.
    """
    db.init_db()
    lookup = _get_pattern_lookup()
    now = datetime.now()

    # Walk each hour in the forecast period and label it idle or not.
    hours: list[tuple[datetime, bool, float]] = []
    for offset in range(hours_ahead):
        dt = now + timedelta(hours=offset)
        dt_rounded = dt.replace(minute=0, second=0, microsecond=0)
        dow = dt_rounded.weekday()
        h = dt_rounded.hour
        pattern = lookup.get((dow, h))
        if pattern is not None and pattern.sample_count > 0:
            is_idle = pattern.activity_probability < _IDLE_PROBABILITY_THRESHOLD
            confidence = 1.0 - pattern.activity_probability
        else:
            # No data -- treat as mildly idle with low confidence.
            is_idle = True
            confidence = 0.5
        hours.append((dt_rounded, is_idle, confidence))

    # Group consecutive idle hours into windows.
    windows: list[dict] = []
    i = 0
    while i < len(hours):
        if not hours[i][1]:
            i += 1
            continue
        # Start of an idle window.
        start_dt = hours[i][0]
        confidences = [hours[i][2]]
        j = i + 1
        while j < len(hours) and hours[j][1]:
            confidences.append(hours[j][2])
            j += 1
        end_dt = hours[j - 1][0] + timedelta(hours=1)
        duration = (end_dt - start_dt).total_seconds() / 3600.0
        windows.append({
            "start": start_dt,
            "end": end_dt,
            "duration_hours": duration,
            "confidence": sum(confidences) / len(confidences),
        })
        i = j

    return windows


def predict_next_return() -> datetime | None:
    """Predict when the user will next become active.

    Starting from the current hour, scans forward through schedule patterns
    to find the next hour with activity probability >= the active threshold.
    Returns ``None`` if no high-activity hour is found within 168 hours
    (one week).
    """
    db.init_db()
    lookup = _get_pattern_lookup()
    now = datetime.now()

    for offset in range(1, 169):  # up to 1 week ahead
        dt = now + timedelta(hours=offset)
        dt_rounded = dt.replace(minute=0, second=0, microsecond=0)
        dow = dt_rounded.weekday()
        h = dt_rounded.hour
        pattern = lookup.get((dow, h))
        if pattern is not None and pattern.activity_probability >= _ACTIVE_PROBABILITY_THRESHOLD:
            return dt_rounded

    return None


def estimate_wasted_quota(hours_ahead: int = 24) -> dict:
    """Estimate how much quota would be wasted during predicted idle windows.

    Returns a dict with:
        * ``idle_hours`` (float) -- total predicted idle hours
        * ``wasted_messages`` (int) -- estimated messages that could have been
          used (based on the quota window configuration)
        * ``wasted_cost_usd`` (float) -- estimated dollar value of wasted
          quota (rough, based on default model costs)
    """
    db.init_db()
    windows = predict_idle_windows(hours_ahead=hours_ahead)

    total_idle_hours = sum(w["duration_hours"] for w in windows)

    # Calculate how many messages would go unused.
    window_hours = config.get("quota", "window_hours", constants.DEFAULT_QUOTA_WINDOW_HOURS)
    messages_per_window = config.get(
        "quota", "messages_per_window", constants.DEFAULT_MESSAGES_PER_WINDOW,
    )
    messages_per_hour = messages_per_window / max(window_hours, 1)
    wasted_messages = int(total_idle_hours * messages_per_hour)

    # Rough cost estimate: average tokens per message * model cost.
    # Use a conservative estimate of ~4000 input + ~1000 output tokens per message.
    model = config.get("claude", "model", constants.DEFAULT_MODEL)
    costs = constants.MODEL_COSTS.get(model, constants.MODEL_COSTS[constants.DEFAULT_MODEL])
    avg_input_tokens = 4000
    avg_output_tokens = 1000
    cost_per_message = (
        (avg_input_tokens / 1_000_000) * costs["input"]
        + (avg_output_tokens / 1_000_000) * costs["output"]
    )
    wasted_cost_usd = round(wasted_messages * cost_per_message, 2)

    return {
        "idle_hours": round(total_idle_hours, 1),
        "wasted_messages": wasted_messages,
        "wasted_cost_usd": wasted_cost_usd,
    }


def predict_idle(hours: int = 24) -> None:
    """CLI display function for idle window predictions.

    Shows predicted idle windows and estimated quota waste.
    """
    db.init_db()
    windows = predict_idle_windows(hours_ahead=hours)
    waste = estimate_wasted_quota(hours_ahead=hours)

    click.echo(f"Idle window predictions (next {hours}h):")
    click.echo()

    if not windows:
        click.echo("  No idle windows predicted -- user appears continuously active.")
        return

    for i, w in enumerate(windows, 1):
        start_str = w["start"].strftime("%a %H:%M")
        end_str = w["end"].strftime("%a %H:%M")
        click.echo(
            f"  {i}. {start_str} - {end_str}  "
            f"({w['duration_hours']:.1f}h, confidence {w['confidence']:.0%})"
        )

    click.echo()
    click.echo("Estimated waste if no autonomous work is scheduled:")
    click.echo(f"  Idle hours:       {waste['idle_hours']}")
    click.echo(f"  Wasted messages:  ~{waste['wasted_messages']}")
    click.echo(f"  Wasted value:     ~${waste['wasted_cost_usd']:.2f}")

    next_return = predict_next_return()
    if next_return is not None:
        click.echo()
        click.echo(f"Predicted next return: {next_return.strftime('%a %H:%M')}")
