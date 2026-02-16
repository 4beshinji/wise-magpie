"""Shared test fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wise_magpie import config, db
from wise_magpie.models import Task, TaskSource, TaskStatus


@pytest.fixture(autouse=True)
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect config/data directory to a temp dir for every test."""
    cfg_dir = tmp_path / "wise-magpie-test"
    cfg_dir.mkdir()
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", cfg_dir / "config.toml")
    db.init_db()
    return cfg_dir


@pytest.fixture
def sample_task() -> Task:
    """Insert a pending task into the DB and return it."""
    task = Task(title="Sample task", description="A test task", source=TaskSource.MANUAL)
    task.id = db.insert_task(task)
    return task


@pytest.fixture
def completed_task(git_repo: Path) -> Task:
    """Insert a completed task with work_branch and work_dir."""
    task = Task(
        title="Completed task",
        description="Done",
        source=TaskSource.MANUAL,
        status=TaskStatus.COMPLETED,
        work_branch="wise-magpie/completed-task",
        work_dir=str(git_repo),
    )
    task.id = db.insert_task(task)
    return task


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo), capture_output=True, check=True,
    )
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo), capture_output=True, check=True,
    )
    return repo
