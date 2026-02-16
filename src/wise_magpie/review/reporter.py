"""Work summary and review reporting."""

from __future__ import annotations

import click

from wise_magpie import db
from wise_magpie.models import TaskStatus
from wise_magpie.worker.sandbox import get_branch_diff, get_branch_log


def list_reviews() -> None:
    """List completed tasks awaiting review."""
    db.init_db()
    tasks = db.get_tasks_by_status(TaskStatus.COMPLETED)

    if not tasks:
        click.echo("No completed tasks awaiting review.")
        return

    click.echo(f"{'ID':>4}  {'Branch':<40}  {'Title'}")
    click.echo("-" * 80)
    for t in tasks:
        branch = t.work_branch or "(no branch)"
        click.echo(f"{t.id:>4}  {branch:<40}  {t.title}")


def show_review(task_id: int) -> None:
    """Show details and diff for a completed task."""
    db.init_db()
    task = db.get_task(task_id)
    if task is None:
        click.echo(f"Task #{task_id} not found.", err=True)
        raise SystemExit(1)

    click.echo(f"Task #{task.id}: {task.title}")
    click.echo(f"Status:  {task.status.value}")
    click.echo(f"Source:  {task.source.value} ({task.source_ref})")
    click.echo(f"Branch:  {task.work_branch or 'N/A'}")
    click.echo(f"Created: {task.created_at}")
    click.echo(f"Started: {task.started_at}")
    click.echo(f"Done:    {task.completed_at}")

    if task.result_summary:
        click.echo(f"\n--- Result Summary ---")
        click.echo(task.result_summary)

    if task.work_branch and task.work_dir:
        click.echo(f"\n--- Commits ---")
        try:
            # Determine base branch (strip wise-magpie/ prefix and task suffix)
            log = get_branch_log(task.work_dir, task.work_branch, "HEAD")
            if log:
                click.echo(log)
            else:
                click.echo("(no commits)")
        except Exception as e:
            click.echo(f"(could not get log: {e})")

        click.echo(f"\n--- Diff ---")
        try:
            diff = get_branch_diff(task.work_dir, task.work_branch, "HEAD")
            if diff:
                click.echo(diff)
            else:
                click.echo("(no changes)")
        except Exception as e:
            click.echo(f"(could not get diff: {e})")
