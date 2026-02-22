"""Tests for daemon/scheduler.py — should_execute() decision logic."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from wise_magpie import db
from wise_magpie.daemon.scheduler import calculate_max_parallel, should_execute
from wise_magpie.models import Task, TaskSource, TaskStatus


def _insert_task(status: TaskStatus = TaskStatus.PENDING) -> Task:
    task = Task(title="test", description="", source=TaskSource.MANUAL, status=status)
    task.id = db.insert_task(task)
    return task


def _default_patches():
    """Return default patch values where all checks pass."""
    return {
        "wise_magpie.daemon.scheduler.check_budget_available": (True, "ok"),
    }


def _patch_all(**overrides):
    """Create a contextmanager that patches scheduler dependencies."""
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


# ---------------------------------------------------------------------------
# calculate_max_parallel
# ---------------------------------------------------------------------------


class TestCalculateMaxParallel:
    """Formula: score = sqrt(quota_ratio * time_ratio), thresholds 0.75/0.50/0.25."""

    def test_full_quota_full_time_gives_max(self):
        # score = sqrt(1.0 * 1.0) = 1.0 → 4
        assert calculate_max_parallel(100.0, 5.0) == 4

    def test_zero_quota_gives_one(self):
        # score = sqrt(0 * 1) = 0 → 1  (no quota headroom)
        assert calculate_max_parallel(0.0, 5.0) == 1

    def test_zero_time_gives_one(self):
        # score = sqrt(1 * 0) = 0 → 1  (window expiring)
        assert calculate_max_parallel(100.0, 0.0) == 1

    def test_both_zero_gives_one(self):
        assert calculate_max_parallel(0.0, 0.0) == 1

    def test_mid_quota_mid_time_gives_three(self):
        # score = sqrt(0.5 * 0.5) = 0.50 → 3
        assert calculate_max_parallel(50.0, 2.5) == 3

    def test_low_quota_low_time_gives_one(self):
        # score = sqrt(0.1 * 0.1) = 0.10 → 1
        assert calculate_max_parallel(10.0, 0.5) == 1

    def test_high_quota_low_time_gives_two(self):
        # score = sqrt(0.9 * 0.1) = sqrt(0.09) ≈ 0.30 → 2
        assert calculate_max_parallel(90.0, 0.5) == 2

    def test_high_quota_high_time_gives_four(self):
        # score = sqrt(0.9 * 0.9) = 0.9 → 4
        assert calculate_max_parallel(90.0, 4.5) == 4

    def test_cap_is_respected(self):
        assert calculate_max_parallel(100.0, 5.0, cap=2) == 2

    def test_cap_one_always_sequential(self):
        assert calculate_max_parallel(100.0, 5.0, cap=1) == 1

    def test_negative_values_clamped(self):
        assert calculate_max_parallel(-10.0, -1.0) == 1

    def test_over_100_pct_quota_treated_as_100(self):
        result = calculate_max_parallel(200.0, 5.0)
        assert result == 4

    def test_threshold_75_boundary(self):
        # score = sqrt(0.75 * 0.75) = 0.75 → 4 (≥ 0.75)
        assert calculate_max_parallel(75.0, 3.75) == 4

    def test_threshold_below_25(self):
        # score = sqrt(0.2 * 0.2) = 0.20 → 1 (< 0.25)
        assert calculate_max_parallel(20.0, 1.0) == 1


# ---------------------------------------------------------------------------
# Check 1: budget
# ---------------------------------------------------------------------------


class TestCheck1Budget:
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

    def test_user_active_does_not_block(self):
        """User activity must not prevent execution — quota is the only gate."""
        _insert_task()
        with _patch_all():
            ok, reason = should_execute()
        assert ok is True  # no activity patches needed — activity is ignored


# ---------------------------------------------------------------------------
# Check 2: pending tasks
# ---------------------------------------------------------------------------


class TestCheck2PendingTasks:
    def test_no_pending_tasks(self):
        with _patch_all():
            ok, reason = should_execute()
        assert ok is False
        assert "pending" in reason.lower()


# ---------------------------------------------------------------------------
# Check 3: parallel slot
# ---------------------------------------------------------------------------


class TestCheck3ParallelSlot:
    def test_no_slot_when_at_limit(self):
        _insert_task(TaskStatus.PENDING)
        _insert_task(TaskStatus.RUNNING)
        with _patch_all():
            with patch("wise_magpie.daemon.scheduler.get_parallel_limit", return_value=1):
                ok, reason = should_execute()
        assert ok is False
        assert "running" in reason.lower()

    def test_slot_available_when_under_limit(self):
        _insert_task(TaskStatus.PENDING)
        _insert_task(TaskStatus.RUNNING)
        with _patch_all():
            with patch("wise_magpie.daemon.scheduler.get_parallel_limit", return_value=4):
                ok, reason = should_execute()
        assert ok is True

    def test_multiple_running_blocks_at_limit(self):
        _insert_task(TaskStatus.PENDING)
        for _ in range(3):
            _insert_task(TaskStatus.RUNNING)
        with _patch_all():
            with patch("wise_magpie.daemon.scheduler.get_parallel_limit", return_value=3):
                ok, reason = should_execute()
        assert ok is False
        assert "3" in reason


# ---------------------------------------------------------------------------
# All checks passing
# ---------------------------------------------------------------------------


class TestAllChecksPassing:
    def test_should_execute_when_all_clear(self):
        _insert_task(TaskStatus.PENDING)
        with _patch_all():
            ok, reason = should_execute()
        assert ok is True
        assert "pending" in reason.lower()

    def test_reason_includes_parallel_info(self):
        _insert_task(TaskStatus.PENDING)
        with _patch_all():
            ok, reason = should_execute()
        assert ok is True
        assert "parallel" in reason.lower()
