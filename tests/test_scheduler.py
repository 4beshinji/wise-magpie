"""Tests for daemon/scheduler.py — should_execute() 6-stage decision logic."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from wise_magpie import db
from wise_magpie.daemon.scheduler import should_execute
from wise_magpie.models import Task, TaskSource, TaskStatus


def _insert_task(status: TaskStatus = TaskStatus.PENDING) -> Task:
    task = Task(title="test", description="", source=TaskSource.MANUAL, status=status)
    task.id = db.insert_task(task)
    return task


def _default_patches():
    """Return a dict of default patch values where all 6 checks pass."""
    return {
        "wise_magpie.daemon.scheduler.is_user_active": False,
        "wise_magpie.daemon.scheduler.get_idle_minutes": 60.0,
        "wise_magpie.daemon.scheduler.predict_next_return": None,
        "wise_magpie.daemon.scheduler.check_budget_available": (True, "ok"),
    }


def _patch_all(**overrides):
    """Create a contextmanager that patches all scheduler dependencies."""
    values = _default_patches()
    values.update(overrides)

    import contextlib

    @contextlib.contextmanager
    def ctx():
        patchers = []
        for target, val in values.items():
            p = patch(target, return_value=val)
            p.start()
            patchers.append(p)
        try:
            yield
        finally:
            for p in patchers:
                p.stop()

    return ctx()


class TestCheck1UserActive:
    def test_user_active_blocks(self):
        _insert_task()
        with _patch_all(**{"wise_magpie.daemon.scheduler.is_user_active": True}):
            ok, reason = should_execute()
        assert ok is False
        assert "active" in reason.lower()


class TestCheck2IdleThreshold:
    def test_not_idle_enough(self):
        _insert_task()
        with _patch_all(**{"wise_magpie.daemon.scheduler.get_idle_minutes": 5.0}):
            ok, reason = should_execute()
        assert ok is False
        assert "idle" in reason.lower()


class TestCheck3ReturnPrediction:
    def test_user_returning_soon(self):
        _insert_task()
        soon = datetime.now() + timedelta(minutes=5)
        with _patch_all(**{"wise_magpie.daemon.scheduler.predict_next_return": soon}):
            ok, reason = should_execute()
        assert ok is False
        assert "return" in reason.lower()

    def test_user_returning_far_away_passes(self):
        _insert_task()
        far = datetime.now() + timedelta(hours=3)
        with _patch_all(**{"wise_magpie.daemon.scheduler.predict_next_return": far}):
            ok, reason = should_execute()
        assert ok is True


class TestCheck4Budget:
    def test_no_budget_blocks(self):
        _insert_task()
        with _patch_all(
            **{
                "wise_magpie.daemon.scheduler.check_budget_available": (
                    False,
                    "Daily limit reached",
                ),
            }
        ):
            ok, reason = should_execute()
        assert ok is False
        assert "limit" in reason.lower() or "budget" in reason.lower()


class TestCheck5PendingTasks:
    def test_no_pending_tasks(self):
        # No tasks inserted
        with _patch_all():
            ok, reason = should_execute()
        assert ok is False
        assert "pending" in reason.lower()


class TestCheck6RunningTask:
    def test_task_already_running(self):
        _insert_task(TaskStatus.PENDING)
        _insert_task(TaskStatus.RUNNING)
        with _patch_all():
            ok, reason = should_execute()
        assert ok is False
        assert "running" in reason.lower()


class TestAllChecksPassing:
    def test_should_execute_when_all_clear(self):
        _insert_task(TaskStatus.PENDING)
        with _patch_all():
            ok, reason = should_execute()
        assert ok is True
        assert "pending" in reason.lower()
