"""Tests for review/reporter.py — list_reviews and show_review."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wise_magpie import db
from wise_magpie.models import Task, TaskSource, TaskStatus
from wise_magpie.review.reporter import list_reviews, show_review


def _insert(
    title: str = "task",
    status: TaskStatus = TaskStatus.COMPLETED,
    work_branch: str = "",
    work_dir: str = "",
) -> Task:
    task = Task(
        title=title,
        description="desc",
        source=TaskSource.MANUAL,
        status=status,
        work_branch=work_branch,
        work_dir=work_dir,
    )
    task.id = db.insert_task(task)
    return task


class TestListReviews:
    def test_empty(self, capsys):
        list_reviews()
        out = capsys.readouterr().out
        assert "No completed tasks" in out

    def test_shows_completed(self, capsys):
        _insert("My task", work_branch="wise-magpie/my-task")
        list_reviews()
        out = capsys.readouterr().out
        assert "My task" in out
        assert "wise-magpie/my-task" in out

    def test_no_branch_label(self, capsys):
        _insert("No branch task")
        list_reviews()
        out = capsys.readouterr().out
        assert "(no branch)" in out


class TestShowReview:
    def test_not_found(self):
        with pytest.raises(SystemExit):
            show_review(999)

    def test_basic_output(self, capsys):
        t = _insert("Detail task", work_branch="wise-magpie/detail")
        show_review(t.id)
        out = capsys.readouterr().out
        assert "Detail task" in out
        assert "completed" in out
        assert "wise-magpie/detail" in out

    def test_with_git_branch(self, git_repo: Path, capsys):
        # Create a work branch with a commit
        subprocess.run(
            ["git", "checkout", "-b", "wise-magpie/review-test"],
            cwd=str(git_repo), capture_output=True, check=True,
        )
        (git_repo / "new_file.py").write_text("print('hello')\n")
        subprocess.run(["git", "add", "."], cwd=str(git_repo), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add new file"],
            cwd=str(git_repo), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "checkout", "master"],
            cwd=str(git_repo), capture_output=True,
        )
        # Fallback to "main" if "master" didn't work
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(git_repo), capture_output=True,
        )

        t = _insert(
            "Git review",
            work_branch="wise-magpie/review-test",
            work_dir=str(git_repo),
        )
        show_review(t.id)
        out = capsys.readouterr().out
        assert "Commits" in out
        assert "Diff" in out
