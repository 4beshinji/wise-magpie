"""Merge/reject execution for reviewed tasks."""

from __future__ import annotations

import click

from wise_magpie import db
from wise_magpie.models import TaskStatus
from wise_magpie.worker.sandbox import delete_branch, get_current_branch, merge_branch


def approve_task(task_id: int) -> None:
    """Approve and merge a completed task's work branch."""
    db.init_db()
    task = db.get_task(task_id)
    if task is None:
        click.echo(f"Task #{task_id} not found.", err=True)
        raise SystemExit(1)

    if task.status != TaskStatus.COMPLETED:
        click.echo(f"Task #{task_id} is not completed (status: {task.status.value}).", err=True)
        raise SystemExit(1)

    if not task.work_branch:
        click.echo(f"Task #{task_id} has no work branch to merge.", err=True)
        raise SystemExit(1)

    if not task.work_dir:
        click.echo(f"Task #{task_id} has no work directory recorded.", err=True)
        raise SystemExit(1)

    target = get_current_branch(task.work_dir)
    click.echo(f"Merging {task.work_branch} into {target}...")

    try:
        merge_branch(task.work_dir, task.work_branch, target)
    except Exception as e:
        click.echo(f"Merge failed: {e}", err=True)
        click.echo("Resolve conflicts manually and re-run, or reject this task.")
        raise SystemExit(1)

    # Clean up work branch after successful merge
    try:
        delete_branch(task.work_dir, task.work_branch)
    except Exception:
        pass  # Branch already merged, not critical

    click.echo(f"Task #{task_id} approved and merged.")


def reject_task(task_id: int) -> None:
    """Reject a completed task and clean up its work branch."""
    db.init_db()
    task = db.get_task(task_id)
    if task is None:
        click.echo(f"Task #{task_id} not found.", err=True)
        raise SystemExit(1)

    if task.status != TaskStatus.COMPLETED:
        click.echo(f"Task #{task_id} is not completed (status: {task.status.value}).", err=True)
        raise SystemExit(1)

    if task.work_branch and task.work_dir:
        click.echo(f"Deleting branch {task.work_branch}...")
        try:
            delete_branch(task.work_dir, task.work_branch)
            click.echo("Branch deleted.")
        except Exception as e:
            click.echo(f"Warning: could not delete branch: {e}")

    task.status = TaskStatus.CANCELLED
    db.update_task(task)
    click.echo(f"Task #{task_id} rejected.")
