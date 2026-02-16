"""Tests for worker components."""

import subprocess
from pathlib import Path

import pytest

from wise_magpie.worker.sandbox import (
    _sanitize_branch_name,
    create_sandbox,
    cleanup_sandbox,
    get_current_branch,
    has_uncommitted_changes,
)
from wise_magpie.worker.executor import build_claude_command
from wise_magpie.worker.monitor import check_budget_available, get_task_budget


def test_sanitize_branch_name():
    assert _sanitize_branch_name("Fix login bug") == "fix-login-bug"
    assert _sanitize_branch_name("a  b  c") == "a-b-c"
    assert _sanitize_branch_name("special!@#chars") == "specialchars"
    # Truncation
    assert len(_sanitize_branch_name("a" * 100)) <= 50


def test_build_claude_command():
    cmd = build_claude_command("do something", "/tmp/work")
    assert "claude" in cmd
    assert "-p" in cmd
    assert "do something" in cmd
    assert "--output-format" in cmd
    assert "json" in cmd


def test_check_budget_available():
    allowed, reason = check_budget_available(0.0)
    # Should be True with fresh DB
    assert isinstance(allowed, bool)
    assert isinstance(reason, str)


def test_get_task_budget():
    budget = get_task_budget()
    assert budget > 0
    assert budget <= 10.0  # Should not exceed daily limit


def test_sandbox_lifecycle(git_repo: Path):
    ctx = create_sandbox(1, "test task", str(git_repo))
    assert ctx.branch_name == "wise-magpie/test-task"
    assert get_current_branch(str(git_repo)) == "wise-magpie/test-task"

    cleanup_sandbox(ctx, keep_branch=True)
    assert get_current_branch(str(git_repo)) == ctx.original_branch


def test_sandbox_no_uncommitted(git_repo: Path):
    # Add uncommitted change
    (git_repo / "dirty.txt").write_text("dirty")
    subprocess.run(["git", "add", "dirty.txt"], cwd=str(git_repo), capture_output=True)

    with pytest.raises(RuntimeError, match="uncommitted"):
        create_sandbox(1, "test", str(git_repo))


def test_has_uncommitted_changes(git_repo: Path):
    assert has_uncommitted_changes(str(git_repo)) is False
    (git_repo / "new.txt").write_text("new")
    subprocess.run(["git", "add", "new.txt"], cwd=str(git_repo), capture_output=True)
    assert has_uncommitted_changes(str(git_repo)) is True
