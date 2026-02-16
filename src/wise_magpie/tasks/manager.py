"""Task queue management (CLI-facing functions)."""

from __future__ import annotations

from datetime import datetime

import click

from wise_magpie import db
from wise_magpie.models import Task, TaskSource, TaskStatus
from wise_magpie.tasks.prioritizer import calculate_priority, reprioritize_all
from wise_magpie.tasks.sources import auto_tasks, git_todos, queue_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_label(status: TaskStatus) -> str:
    """Human-readable coloured label for a task status."""
    return status.value


def _truncate(text: str, width: int = 50) -> str:
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_task(title: str, description: str = "", priority: float = 0.0) -> Task:
    """Create a new manual task, insert it into the DB, and echo confirmation."""
    db.init_db()

    task = Task(
        title=title,
        description=description,
        source=TaskSource.MANUAL,
        priority=priority,
        created_at=datetime.now(),
    )
    if priority == 0.0:
        task.priority = calculate_priority(task)

    task_id = db.insert_task(task)
    task.id = task_id

    click.echo(f"Added task #{task_id}: {title} (priority {task.priority:.1f})")
    return task


def list_tasks(status_filter: str | None = None) -> list[Task]:
    """Retrieve tasks from the DB and display them as a table.

    *status_filter* can be a :class:`TaskStatus` value string (e.g.
    ``"pending"``) or ``None`` to list all tasks.
    """
    db.init_db()

    if status_filter and status_filter != "all":
        try:
            status = TaskStatus(status_filter)
        except ValueError:
            click.echo(f"Unknown status: {status_filter}")
            return []
        tasks = db.get_tasks_by_status(status)
    else:
        tasks = db.get_all_tasks()

    if not tasks:
        click.echo("No tasks found.")
        return tasks

    # Table header
    click.echo(
        f"{'ID':>4}  {'Status':<10}  {'Pri':>5}  {'Source':<10}  {'Title'}"
    )
    click.echo("-" * 72)

    for t in tasks:
        click.echo(
            f"{t.id or 0:>4}  "
            f"{_status_label(t.status):<10}  "
            f"{t.priority:>5.1f}  "
            f"{t.source.value:<10}  "
            f"{_truncate(t.title)}"
        )

    click.echo(f"\n{len(tasks)} task(s) total.")
    return tasks


def scan_tasks(path: str) -> int:
    """Run all source scanners, deduplicate, insert new tasks, and reprioritize.

    Returns the number of newly inserted tasks.
    """
    db.init_db()

    # Collect candidates from every scanner
    found: list[Task] = []
    found.extend(git_todos.scan(path))
    found.extend(queue_file.scan(path))
    found.extend(auto_tasks.scan(path))

    click.echo(f"Scanned: found {len(found)} candidate task(s).")

    # Build a set of existing (source, source_ref) pairs for dedup
    existing_tasks = db.get_all_tasks()
    existing_keys: set[tuple[str, str]] = {
        (t.source.value, t.source_ref) for t in existing_tasks
    }

    new_count = 0
    for task in found:
        key = (task.source.value, task.source_ref)
        if key in existing_keys:
            continue
        task.priority = calculate_priority(task)
        task_id = db.insert_task(task)
        task.id = task_id
        existing_keys.add(key)
        new_count += 1

    # Reprioritize everything so scores stay consistent
    reprioritize_all()

    click.echo(f"Inserted {new_count} new task(s).")
    return new_count


def remove_task(task_id: int) -> bool:
    """Delete a task from the DB. Fails if the task is currently running."""
    db.init_db()

    task = db.get_task(task_id)
    if task is None:
        click.echo(f"Task #{task_id} not found.")
        return False

    if task.status == TaskStatus.RUNNING:
        click.echo(f"Cannot remove task #{task_id}: it is currently running.")
        return False

    db.delete_task(task_id)
    click.echo(f"Removed task #{task_id}: {task.title}")
    return True


def get_next_task() -> Task | None:
    """Return the highest-priority pending task, or ``None``."""
    db.init_db()

    pending = db.get_tasks_by_status(TaskStatus.PENDING)
    if not pending:
        return None
    # get_tasks_by_status already sorts by priority DESC
    return pending[0]
