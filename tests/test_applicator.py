"""Tests for review/applicator.py — approve_task and reject_task."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wise_magpie import db
from wise_magpie.models import Task, TaskSource, TaskStatus
from wise_magpie.review.applicator import approve_task, reject_task
from wise_magpie.worker.sandbox import get_current_branch


def _insert(
    status: TaskStatus = TaskStatus.COMPLETED,
    work_branch: str = "",
    work_dir: str = "",
) -> Task:
    task = Task(
        title="test task",
        description="",
        source=TaskSource.MANUAL,
        status=status,
        work_branch=work_branch,
        work_dir=work_dir,
    )
    task.id = db.insert_task(task)
    return task


def _create_work_branch(repo: Path, branch: str) -> None:
    """Create a branch with a commit and return to the original branch."""
    original = get_current_branch(str(repo))
    subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=str(repo), capture_output=True, check=True,
    )
    (repo / "work.txt").write_text("work done\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "task work"],
        cwd=str(repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "checkout", original],
        cwd=str(repo), capture_output=True, check=True,
    )


class TestApproveGuards:
    def test_not_found(self):
        with pytest.raises(SystemExit):
            approve_task(999)

    def test_not_completed(self):
        t = _insert(status=TaskStatus.PENDING)
        with pytest.raises(SystemExit):
            approve_task(t.id)

    def test_no_branch(self):
        t = _insert(work_dir="/tmp")
        with pytest.raises(SystemExit):
            approve_task(t.id)

    def test_no_work_dir(self):
        t = _insert(work_branch="wise-magpie/test")
        with pytest.raises(SystemExit):
            approve_task(t.id)


class TestApproveSuccess:
    def test_merge_and_cleanup(self, git_repo: Path):
        branch = "wise-magpie/approve-test"
        _create_work_branch(git_repo, branch)

        t = _insert(work_branch=branch, work_dir=str(git_repo))
        approve_task(t.id)

        # Branch should be deleted after merge
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=str(git_repo), capture_output=True, text=True,
        )
        assert result.stdout.strip() == ""

        # Merged file should exist
        assert (git_repo / "work.txt").exists()


class TestRejectGuards:
    def test_not_found(self):
        with pytest.raises(SystemExit):
            reject_task(999)

    def test_not_completed(self):
        t = _insert(status=TaskStatus.RUNNING)
        with pytest.raises(SystemExit):
            reject_task(t.id)


class TestRejectSuccess:
    def test_deletes_branch_and_cancels(self, git_repo: Path):
        branch = "wise-magpie/reject-test"
        _create_work_branch(git_repo, branch)

        t = _insert(work_branch=branch, work_dir=str(git_repo))
        reject_task(t.id)

        # Branch deleted
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            cwd=str(git_repo), capture_output=True, text=True,
        )
        assert result.stdout.strip() == ""

        # Status is CANCELLED
        updated = db.get_task(t.id)
        assert updated.status == TaskStatus.CANCELLED

    def test_reject_without_branch(self):
        t = _insert()
        reject_task(t.id)
        updated = db.get_task(t.id)
        assert updated.status == TaskStatus.CANCELLED
