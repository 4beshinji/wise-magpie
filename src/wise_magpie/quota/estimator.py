"""Quota estimation: track remaining quota and budget availability."""

from __future__ import annotations

from datetime import datetime, timedelta

import click

from wise_magpie import config, constants, db
from wise_magpie.constants import MODEL_QUOTAS, resolve_model
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


def get_model_limit(model: str) -> int:
    """Return the per-window message limit for *model*.

    Resolution order:
      1. config [quota.limits] (alias keys: opus/sonnet/haiku)
      2. constants.MODEL_QUOTAS
      3. config [quota] messages_per_window (legacy)
      4. DEFAULT_MESSAGES_PER_WINDOW
    """
    cfg = config.load_config()
    limits = cfg.get("quota", {}).get("limits", {})

    # Check alias keys in config (opus, sonnet, haiku)
    for alias, full_id in constants.MODEL_ALIASES.items():
        if full_id == model and alias in limits:
            return int(limits[alias])

    # Check full model ID in config
    if model in limits:
        return int(limits[model])

    # Fallback to constants
    if model in MODEL_QUOTAS:
        return MODEL_QUOTAS[model]

    # Legacy fallback
    return config.get("quota", "messages_per_window", constants.DEFAULT_MESSAGES_PER_WINDOW)


def estimate_remaining(model: str | None = None) -> dict:
    """Estimate remaining quota in the current window.

    If *model* is given, estimates remaining quota for that specific model.
    Otherwise uses the configured default model (backward compatible).

    Returns a dict with keys:
        window_start, window_end, estimated_limit, used, remaining,
        remaining_pct, safety_reserved, available_for_autonomous,
        model, model_limit.
    """
    db.init_db()

    window = _ensure_window()
    window_end = window.window_start + timedelta(hours=window.window_hours)

    # Resolve model
    if model is None:
        cfg = config.load_config()
        model = resolve_model(cfg.get("claude", {}).get("model", constants.DEFAULT_MODEL))

    model_limit = get_model_limit(model)

    # Check for per-model correction
    correction = db.get_latest_quota_correction(window.id, model) if window.id else None  # type: ignore[arg-type]

    if correction is not None:
        corrected_at = correction["corrected_at"]
        post_correction_count = db.get_model_usage_count(model, corrected_at)
        remaining = max(correction["remaining"] - post_correction_count, 0)
        used = model_limit - remaining
    elif window.user_correction is not None and model == resolve_model(
        config.get("claude", "model", constants.DEFAULT_MODEL)
    ):
        # Legacy per-window correction (backward compat for default model)
        post_correction_records = db.get_usage_since(window.corrected_at)  # type: ignore[arg-type]
        used_after_correction = len(post_correction_records)
        remaining = max(window.user_correction - used_after_correction, 0)
        used = model_limit - remaining
    else:
        used = db.get_model_usage_count(model, window.window_start)
        remaining = max(model_limit - used, 0)

    remaining_pct = (remaining / model_limit * 100) if model_limit else 0.0

    safety_margin = config.get("quota", "safety_margin", constants.QUOTA_SAFETY_MARGIN)
    safety_reserved = int(model_limit * safety_margin)
    available_for_autonomous = max(remaining - safety_reserved, 0)

    return {
        "window_start": window.window_start,
        "window_end": window_end,
        "estimated_limit": model_limit,
        "used": used,
        "remaining": remaining,
        "remaining_pct": remaining_pct,
        "safety_reserved": safety_reserved,
        "available_for_autonomous": available_for_autonomous,
        "model": model,
        "model_limit": model_limit,
    }


def show_quota() -> None:
    """Display a human-readable per-model quota summary."""
    db.init_db()

    window = _ensure_window()
    window_end = window.window_start + timedelta(hours=window.window_hours)

    click.echo("Quota Status")
    click.echo("=" * 60)
    click.echo(f"Window: {window.window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')}")
    click.echo()

    # Per-model table
    click.echo(f"  {'Model':<10}  {'Limit':>6}  {'Used':>6}  {'Remaining':>12}")
    click.echo("  " + "-" * 42)

    for alias in ("opus", "sonnet", "haiku"):
        full_id = constants.MODEL_ALIASES[alias]
        info = estimate_remaining(model=full_id)
        click.echo(
            f"  {alias:<10}  {info['model_limit']:>6}  {info['used']:>6}  "
            f"{info['remaining']:>5} ({info['remaining_pct']:.0f}%)"
        )

    click.echo()
    # Show default model's autonomous availability
    default_info = estimate_remaining()
    click.echo(f"Safety margin: {default_info['safety_reserved']} messages reserved")
    click.echo(f"Autonomous:    {default_info['available_for_autonomous']} messages available")


def has_budget_for_task(estimated_cost: float, model: str | None = None) -> bool:
    """Check whether there is budget for a task of the given cost.

    Considers both the overall quota remaining and the daily autonomous
    spending limit.
    """
    db.init_db()

    info = estimate_remaining(model=model)
    if info["available_for_autonomous"] <= 0:
        return False

    max_daily = config.get("budget", "max_daily_usd", constants.MAX_DAILY_AUTONOMOUS_USD)
    daily_spent = db.get_daily_autonomous_cost(datetime.now())
    if daily_spent + estimated_cost > max_daily:
        return False

    return True
