"""Tests for task management."""

import tempfile
from pathlib import Path

from wise_magpie import db
from wise_magpie.models import Task, TaskSource, TaskStatus
from wise_magpie.tasks.prioritizer import calculate_priority
from wise_magpie.tasks.manager import add_task, get_next_task, remove_task
from wise_magpie.tasks.sources.queue_file import scan as scan_queue


def test_calculate_priority_manual():
    task = Task(title="Fix login bug", source=TaskSource.MANUAL)
    score = calculate_priority(task)
    assert score > 0


def test_calculate_priority_keywords():
    bug_task = Task(title="Fix critical bug", source=TaskSource.GIT_TODO)
    doc_task = Task(title="Update documentation", source=TaskSource.GIT_TODO)
    assert calculate_priority(bug_task) > calculate_priority(doc_task)


def test_add_task():
    task = add_task("Test task", "description", 0.0)
    assert task.id is not None
    assert task.priority > 0


def test_get_next_task():
    add_task("Low priority", "", 10.0)
    add_task("High priority", "", 90.0)
    nxt = get_next_task()
    assert nxt is not None
    assert nxt.title == "High priority"


def test_remove_task():
    task = add_task("To remove", "", 50.0)
    assert remove_task(task.id) is True
    assert db.get_task(task.id) is None


def test_remove_running_task():
    task = add_task("Running task", "", 50.0)
    task.status = TaskStatus.RUNNING
    db.update_task(task)
    assert remove_task(task.id) is False


def test_scan_queue_file(tmp_path: Path):
    queue_file = tmp_path / ".wise-magpie-tasks"
    queue_file.write_text(
        "# Task list\n"
        "- [ ] Implement feature A\n"
        "- [x] Already done\n"
        "- [ ] Fix bug B\n"
    )
    tasks = scan_queue(str(tmp_path))
    assert len(tasks) == 2
    assert tasks[0].title == "Implement feature A"
    assert tasks[1].title == "Fix bug B"
    assert all(t.source == TaskSource.QUEUE_FILE for t in tasks)


def test_scan_queue_file_missing(tmp_path: Path):
    tasks = scan_queue(str(tmp_path))
    assert tasks == []
