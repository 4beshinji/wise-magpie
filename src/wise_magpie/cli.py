"""Click CLI command definitions for wise-magpie."""

from __future__ import annotations

import click

from wise_magpie import __version__


@click.group()
@click.version_option(version=__version__, prog_name="wise-magpie")
def main() -> None:
    """wise-magpie: Maximize Claude Max quota utilization during idle time."""


# --- Config commands ---

@main.group()
def config() -> None:
    """Manage configuration."""


@config.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing config")
def config_init(force: bool) -> None:
    """Create default configuration file."""
    from wise_magpie.config import init_config
    try:
        path = init_config(force=force)
        click.echo(f"Config created: {path}")
    except FileExistsError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@config.command("show")
def config_show() -> None:
    """Show current configuration."""
    from wise_magpie.config import CONFIG_FILE, load_config
    if not CONFIG_FILE.exists():
        click.echo(f"No config file found at {CONFIG_FILE}", err=True)
        click.echo("Run 'wise-magpie config init' to create one.", err=True)
        raise SystemExit(1)
    click.echo(CONFIG_FILE.read_text())


@config.command("edit")
def config_edit() -> None:
    """Open configuration in editor."""
    from wise_magpie.config import CONFIG_FILE
    if not CONFIG_FILE.exists():
        click.echo(f"No config file found at {CONFIG_FILE}", err=True)
        click.echo("Run 'wise-magpie config init' to create one.", err=True)
        raise SystemExit(1)
    click.edit(filename=str(CONFIG_FILE))


# --- Quota commands (Phase 2) ---

@main.group()
def quota() -> None:
    """Quota tracking and estimation."""


@quota.command("show")
def quota_show() -> None:
    """Show estimated remaining quota."""
    from wise_magpie.quota.estimator import show_quota
    show_quota()


@quota.command("correct")
@click.option(
    "--session", type=click.IntRange(0, 100), default=None,
    help='Percentage from Claude\'s "/usage" → "Current session X%"',
)
@click.option(
    "--week-all", "week_all", type=click.IntRange(0, 100), default=None,
    help='Percentage from Claude\'s "/usage" → "Current week (all models) X%"',
)
@click.option(
    "--week-sonnet", "week_sonnet", type=click.IntRange(0, 100), default=None,
    help='Percentage from Claude\'s "/usage" → "Current week (sonnet only) X%"',
)
def quota_correct(session: int | None, week_all: int | None, week_sonnet: int | None) -> None:
    """Sync quota with values shown by Claude's /usage command.

    Run /usage inside Claude, then enter the percentages here:

    \b
      wise-magpie quota correct --session 12 --week-all 28 --week-sonnet 4

    Each option is independent; supply only what you want to update.
    """
    from wise_magpie.quota.corrections import apply_correction
    if session is None and week_all is None and week_sonnet is None:
        import click as _click
        raise _click.UsageError(
            "Provide at least one option: --session, --week-all, or --week-sonnet"
        )
    apply_correction(session=session, week_all=week_all, week_sonnet=week_sonnet)


@quota.command("sync")
def quota_sync() -> None:
    """Fetch current quota from Anthropic API and apply automatically.

    Reads ~/.claude/.credentials.json and calls the same endpoint that
    Claude Code's /usage command uses.  No manual input required.
    """
    from wise_magpie.quota.corrections import auto_sync
    if auto_sync():
        from wise_magpie.quota.estimator import show_quota
        show_quota()
    else:
        click.echo(
            "Sync failed. Check that ~/.claude/.credentials.json exists "
            "and you have network access.",
            err=True,
        )
        raise SystemExit(1)


@quota.command("history")
@click.option("--days", default=7, help="Number of days to show")
def quota_history(days: int) -> None:
    """Show usage history."""
    from wise_magpie.quota.tracker import show_history
    show_history(days)


_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_FULL = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _parse_day(value: str) -> int:
    """Parse a weekday name or integer (0=Mon) into an integer 0-6."""
    v = value.strip().lower()
    if v in _DAY_NAMES:
        return _DAY_NAMES.index(v)
    if v in _DAY_FULL:
        return _DAY_FULL.index(v)
    try:
        n = int(v)
        if 0 <= n <= 6:
            return n
    except ValueError:
        pass
    raise click.BadParameter(
        f"Expected a weekday name (mon-sun) or integer 0-6, got: {value!r}"
    )


@quota.command("reset-time")
@click.option(
    "--day", default=None,
    help="Day of week the weekly quota resets (mon-sun or 0-6, UTC). Default: mon",
)
@click.option(
    "--hour", type=click.IntRange(0, 23), default=None,
    help="Hour (UTC, 0-23) at which the weekly quota resets. Default: 0",
)
def quota_reset_time(day: str | None, hour: int | None) -> None:
    """Set the weekly quota reset schedule used for budget projection.

    \b
    Examples:
      wise-magpie quota reset-time --day mon --hour 0
      wise-magpie quota reset-time --day 1 --hour 9
      wise-magpie quota reset-time --hour 6
    """
    from wise_magpie.config import set_value

    if day is None and hour is None:
        raise click.UsageError("Provide at least one of --day or --hour")

    if day is not None:
        day_int = _parse_day(day)
        set_value("quota", "weekly_reset_day", day_int)
        click.echo(f"Weekly reset day set to {_DAY_NAMES[day_int].capitalize()} ({day_int})")

    if hour is not None:
        set_value("quota", "weekly_reset_hour", hour)
        click.echo(f"Weekly reset hour set to {hour:02d}:00 UTC")


# --- Schedule commands (Phase 3) ---

@main.group()
def schedule() -> None:
    """Activity patterns and predictions."""


@schedule.command("show")
def schedule_show() -> None:
    """Show learned activity patterns."""
    from wise_magpie.patterns.schedule import show_patterns
    show_patterns()


@schedule.command("predict")
@click.option("--hours", default=24, help="Hours to predict ahead")
def schedule_predict(hours: int) -> None:
    """Predict idle windows and potential waste."""
    from wise_magpie.patterns.predictor import predict_idle
    predict_idle(hours)


# --- Task commands (Phase 4) ---

@main.group()
def tasks() -> None:
    """Task queue management."""


@tasks.command("list")
@click.option("--status", type=click.Choice(["pending", "running", "completed", "failed", "all"]), default="all")
def tasks_list(status: str) -> None:
    """List tasks in the queue."""
    from wise_magpie.tasks.manager import list_tasks
    list_tasks(status)


@tasks.command("add")
@click.argument("title")
@click.option("--description", "-d", default="", help="Task description")
@click.option("--priority", "-p", type=float, default=0.0, help="Priority score")
@click.option("--model", "-m", default="", help="Model to use (opus/sonnet/haiku or auto)")
def tasks_add(title: str, description: str, priority: float, model: str) -> None:
    """Add a task to the queue."""
    from wise_magpie.tasks.manager import add_task
    add_task(title, description, priority, model=model)


@tasks.command("scan")
@click.option("--path", default=".", help="Path to scan for tasks")
def tasks_scan(path: str) -> None:
    """Scan for tasks in git repository."""
    from wise_magpie.tasks.manager import scan_tasks
    scan_tasks(path)


@tasks.command("remove")
@click.argument("task_id", type=int)
def tasks_remove(task_id: int) -> None:
    """Remove a task from the queue."""
    from wise_magpie.tasks.manager import remove_task
    remove_task(task_id)


# --- Review commands (Phase 7) ---

@main.group()
def review() -> None:
    """Review completed autonomous work."""


@review.command("list")
def review_list() -> None:
    """List completed tasks awaiting review."""
    from wise_magpie.review.reporter import list_reviews
    list_reviews()


@review.command("show")
@click.argument("task_id", type=int)
def review_show(task_id: int) -> None:
    """Show details and diff for a completed task."""
    from wise_magpie.review.reporter import show_review
    show_review(task_id)


@review.command("approve")
@click.argument("task_id", type=int)
def review_approve(task_id: int) -> None:
    """Approve and merge a completed task."""
    from wise_magpie.review.applicator import approve_task
    approve_task(task_id)


@review.command("reject")
@click.argument("task_id", type=int)
def review_reject(task_id: int) -> None:
    """Reject and clean up a completed task."""
    from wise_magpie.review.applicator import reject_task
    reject_task(task_id)


# --- Daemon commands (Phase 6) ---

@main.command()
@click.option("--foreground", is_flag=True, help="Run in foreground instead of daemonizing")
def start(foreground: bool) -> None:
    """Start the wise-magpie daemon."""
    from wise_magpie.daemon.runner import start_daemon
    start_daemon(foreground)


@main.command()
def stop() -> None:
    """Stop the wise-magpie daemon."""
    from wise_magpie.daemon.runner import stop_daemon
    stop_daemon()


@main.command()
def status() -> None:
    """Show current status (quota, daemon, running tasks)."""
    from wise_magpie.daemon.runner import show_status
    show_status()
