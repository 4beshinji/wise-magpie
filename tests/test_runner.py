"""Tests for daemon/runner.py — PID management, _run_single_task, show_status."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from unittest.mock import patch

from wise_magpie import db
from wise_magpie.daemon.runner import (
    _is_running,
    _pid_file,
    _remove_pid,
    _run_single_task,
    _write_pid,
    show_status,
)
from wise_magpie.models import Task, TaskSource, TaskStatus


# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------


class TestPidManagement:
    def test_write_and_read(self):
        assert _is_running() is None
        _write_pid()
        assert _is_running() == os.getpid()
        _remove_pid()
        assert _is_running() is None

    def test_stale_pid_cleaned(self):
        pf = _pid_file()
        pf.write_text("99999999")  # Non-existent PID
        assert _is_running() is None
        assert not pf.exists()

    def test_remove_missing_is_noop(self):
        _remove_pid()  # Should not raise


# ---------------------------------------------------------------------------
# _run_single_task
# ---------------------------------------------------------------------------


@dataclass
class _FakeResult:
    success: bool = True
    output: str = "done"
    cost_usd: float = 0.01
    input_tokens: int = 100
    output_tokens: int = 200
    duration_seconds: float = 1.0
    error: str = ""


def _make_task(work_dir: str = "", git: bool = False) -> Task:
    task = Task(
        title="runner test",
        description="desc",
        source=TaskSource.MANUAL,
        status=TaskStatus.PENDING,
        work_dir=work_dir,
    )
    task.id = db.insert_task(task)
    return task


class TestRunSingleTask:
    @patch("wise_magpie.daemon.runner.report_execution")
    @patch("wise_magpie.daemon.runner.execute_task", return_value=_FakeResult())
    @patch("wise_magpie.daemon.runner.get_task_budget", return_value=2.0)
    @patch("wise_magpie.daemon.runner.select_model", return_value="claude-sonnet-4-5-20250929")
    def test_success(self, mock_model, mock_budget, mock_exec, mock_report, tmp_path):
        task = _make_task(work_dir=str(tmp_path))
        _run_single_task(task)
        updated = db.get_task(task.id)
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result_summary == "done"
        mock_report.assert_called_once()

    @patch("wise_magpie.daemon.runner.report_execution")
    @patch(
        "wise_magpie.daemon.runner.execute_task",
        return_value=_FakeResult(success=False, error="timeout"),
    )
    @patch("wise_magpie.daemon.runner.get_task_budget", return_value=2.0)
    @patch("wise_magpie.daemon.runner.select_model", return_value="claude-sonnet-4-5-20250929")
    def test_failure(self, mock_model, mock_budget, mock_exec, mock_report, tmp_path):
        task = _make_task(work_dir=str(tmp_path))
        _run_single_task(task)
        updated = db.get_task(task.id)
        assert updated.status == TaskStatus.FAILED
        assert "timeout" in updated.result_summary

    @patch("wise_magpie.daemon.runner.report_execution")
    @patch("wise_magpie.daemon.runner.execute_task", side_effect=RuntimeError("boom"))
    @patch("wise_magpie.daemon.runner.get_task_budget", return_value=2.0)
    @patch("wise_magpie.daemon.runner.select_model", return_value="claude-sonnet-4-5-20250929")
    def test_exception(self, mock_model, mock_budget, mock_exec, mock_report, tmp_path):
        task = _make_task(work_dir=str(tmp_path))
        _run_single_task(task)
        updated = db.get_task(task.id)
        assert updated.status == TaskStatus.FAILED
        assert "boom" in updated.result_summary

    @patch("wise_magpie.daemon.runner.report_execution")
    @patch("wise_magpie.daemon.runner.execute_task", return_value=_FakeResult())
    @patch("wise_magpie.daemon.runner.get_task_budget", return_value=2.0)
    @patch("wise_magpie.daemon.runner.select_model", return_value="claude-sonnet-4-5-20250929")
    def test_git_branch_created(
        self, mock_model, mock_budget, mock_exec, mock_report, git_repo
    ):
        task = _make_task(work_dir=str(git_repo))
        _run_single_task(task)
        updated = db.get_task(task.id)
        assert updated.work_branch.startswith("wise-magpie/")
        assert updated.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# show_status
# ---------------------------------------------------------------------------


class TestShowStatus:
    @patch("wise_magpie.patterns.activity.is_user_active", return_value=False)
    @patch("wise_magpie.patterns.activity.get_idle_minutes", return_value=42.0)
    @patch(
        "wise_magpie.quota.estimator.estimate_remaining",
        return_value={
            "remaining": 100,
            "estimated_limit": 225,
            "remaining_pct": 44.4,
            "available_for_autonomous": 66,
        },
    )
    def test_stopped_daemon(self, mock_est, mock_idle, mock_active, capsys):
        show_status()
        out = capsys.readouterr().out
        assert "stopped" in out
        assert "Tasks:" in out

    @patch("wise_magpie.patterns.activity.is_user_active", return_value=True)
    @patch("wise_magpie.patterns.activity.get_idle_minutes", return_value=0.0)
    @patch(
        "wise_magpie.quota.estimator.estimate_remaining",
        return_value={
            "remaining": 200,
            "estimated_limit": 225,
            "remaining_pct": 88.9,
            "available_for_autonomous": 166,
        },
    )
    def test_active_user(self, mock_est, mock_idle, mock_active, capsys):
        show_status()
        out = capsys.readouterr().out
        assert "user active" in out

    @patch("wise_magpie.patterns.activity.is_user_active", return_value=False)
    @patch("wise_magpie.patterns.activity.get_idle_minutes", return_value=10.0)
    @patch(
        "wise_magpie.quota.estimator.estimate_remaining",
        return_value={
            "remaining": 150,
            "estimated_limit": 225,
            "remaining_pct": 66.7,
            "available_for_autonomous": 116,
        },
    )
    def test_running_task_shown(self, mock_est, mock_idle, mock_active, capsys):
        task = Task(
            title="active task",
            description="",
            source=TaskSource.MANUAL,
            status=TaskStatus.RUNNING,
        )
        task.id = db.insert_task(task)
        show_status()
        out = capsys.readouterr().out
        assert "1 running" in out
        assert "active task" in out

    @patch("wise_magpie.patterns.activity.is_user_active", return_value=False)
    @patch("wise_magpie.patterns.activity.get_idle_minutes", return_value=42.0)
    @patch(
        "wise_magpie.quota.estimator.estimate_remaining",
        return_value={
            "remaining": 100,
            "estimated_limit": 225,
            "remaining_pct": 44.4,
            "available_for_autonomous": 66,
        },
    )
    def test_parallel_limit_shown(self, mock_est, mock_idle, mock_active, capsys):
        show_status()
        out = capsys.readouterr().out
        assert "parallel" in out.lower()


# ---------------------------------------------------------------------------
# Parallel execution via threading
# ---------------------------------------------------------------------------


@dataclass
class _FakeResultParallel:
    success: bool = True
    output: str = "done"
    cost_usd: float = 0.01
    input_tokens: int = 100
    output_tokens: int = 200
    duration_seconds: float = 0.1
    error: str = ""


class TestParallelExecution:
    """Verify _run_single_task is safe to call from multiple threads concurrently."""

    @patch("wise_magpie.daemon.runner.report_execution")
    @patch("wise_magpie.daemon.runner.execute_task", return_value=_FakeResultParallel())
    @patch("wise_magpie.daemon.runner.get_task_budget", return_value=2.0)
    @patch("wise_magpie.daemon.runner.select_model", return_value="claude-sonnet-4-5-20250929")
    def test_two_tasks_run_concurrently(
        self, mock_model, mock_budget, mock_exec, mock_report, tmp_path
    ):
        """Two tasks launched in separate threads both complete successfully."""
        tasks = []
        for i in range(2):
            t = Task(
                title=f"parallel task {i}",
                description="",
                source=TaskSource.MANUAL,
                status=TaskStatus.PENDING,
                work_dir=str(tmp_path),
            )
            t.id = db.insert_task(t)
            tasks.append(t)

        errors: list[Exception] = []

        def run(task: Task) -> None:
            try:
                _run_single_task(task)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run, args=(t,)) for t in tasks]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"
        assert mock_exec.call_count == 2

        for task in tasks:
            updated = db.get_task(task.id)
            assert updated.status == TaskStatus.COMPLETED
