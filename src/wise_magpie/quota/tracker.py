"""Usage tracking: record API usage and display history."""

from __future__ import annotations

from datetime import datetime, timedelta

import click

from wise_magpie import config, constants, db
from wise_magpie.models import UsageRecord


def record_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    task_id: int | None = None,
    autonomous: bool = False,
) -> int:
    """Record a usage event, calculating cost from MODEL_COSTS.

    Returns the inserted record id.
    """
    db.init_db()

    costs = constants.MODEL_COSTS.get(model, constants.MODEL_COSTS[constants.DEFAULT_MODEL])
    cost_usd = (
        input_tokens * costs["input"] / 1_000_000
        + output_tokens * costs["output"] / 1_000_000
    )

    record = UsageRecord(
        timestamp=datetime.now(),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        task_id=task_id,
        autonomous=autonomous,
    )
    return db.insert_usage(record)


def show_history(days: int) -> None:
    """Display a table of usage records for the last *days* days."""
    db.init_db()

    since = datetime.now() - timedelta(days=days)
    records = db.get_usage_since(since)

    if not records:
        click.echo(f"No usage records in the last {days} day(s).")
        return

    # Header
    click.echo(
        f"{'Date':<20}  {'Model':<32}  {'Input':>8}  {'Output':>8}  "
        f"{'Cost ($)':>9}  {'Auto':>4}"
    )
    click.echo("-" * 90)

    total_input = 0
    total_output = 0
    total_cost = 0.0

    for r in records:
        date_str = r.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        auto_flag = "Y" if r.autonomous else ""
        click.echo(
            f"{date_str:<20}  {r.model:<32}  {r.input_tokens:>8}  {r.output_tokens:>8}  "
            f"{r.cost_usd:>9.4f}  {auto_flag:>4}"
        )
        total_input += r.input_tokens
        total_output += r.output_tokens
        total_cost += r.cost_usd

    click.echo("-" * 90)
    click.echo(
        f"{'TOTAL':<20}  {'':<32}  {total_input:>8}  {total_output:>8}  "
        f"{total_cost:>9.4f}"
    )


def get_usage_summary(hours: int = 24) -> dict:
    """Return a summary dict for the last *hours* hours.

    Keys: total_cost, total_input_tokens, total_output_tokens,
          request_count, autonomous_cost.
    """
    db.init_db()

    since = datetime.now() - timedelta(hours=hours)
    records = db.get_usage_since(since)

    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    autonomous_cost = 0.0

    for r in records:
        total_cost += r.cost_usd
        total_input_tokens += r.input_tokens
        total_output_tokens += r.output_tokens
        if r.autonomous:
            autonomous_cost += r.cost_usd

    return {
        "total_cost": total_cost,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "request_count": len(records),
        "autonomous_cost": autonomous_cost,
    }
