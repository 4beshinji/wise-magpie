"""Branch isolation and working directory management."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SandboxContext:
    """Context for an isolated task execution environment."""
    task_id: int
    task_name: str
    repo_path: str
    branch_name: str
    original_branch: str


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _sanitize_branch_name(name: str) -> str:
    """Convert a task name to a valid git branch name."""
    safe = name.lower().strip()
    safe = safe.replace(" ", "-")
    # Keep only alphanumeric, hyphens, underscores, slashes
    safe = "".join(c for c in safe if c.isalnum() or c in "-_/")
    # Collapse multiple hyphens
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-")[:50]


def get_current_branch(repo_path: str) -> str:
    """Get the current git branch name."""
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return result.stdout.strip()


def has_uncommitted_changes(repo_path: str) -> bool:
    """Check if the repo has uncommitted changes."""
    result = _run_git(["status", "--porcelain"], cwd=repo_path)
    return bool(result.stdout.strip())


def create_sandbox(task_id: int, task_name: str, repo_path: str) -> SandboxContext:
    """Create an isolated branch for task execution.

    Creates a new branch from the current HEAD and checks it out.
    Raises if there are uncommitted changes.
    """
    if not Path(repo_path).joinpath(".git").exists():
        raise RuntimeError(f"Not a git repository: {repo_path}")

    if has_uncommitted_changes(repo_path):
        raise RuntimeError(
            f"Repository has uncommitted changes: {repo_path}. "
            "Commit or stash before running autonomous tasks."
        )

    original_branch = get_current_branch(repo_path)
    branch_name = f"wise-magpie/{_sanitize_branch_name(task_name)}"

    # Check if branch already exists
    result = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.stdout.strip():
        # Branch exists, add task_id suffix
        branch_name = f"{branch_name}-{task_id}"

    _run_git(["checkout", "-b", branch_name], cwd=repo_path)

    return SandboxContext(
        task_id=task_id,
        task_name=task_name,
        repo_path=repo_path,
        branch_name=branch_name,
        original_branch=original_branch,
    )


def cleanup_sandbox(ctx: SandboxContext, keep_branch: bool = True) -> None:
    """Switch back to the original branch.

    If keep_branch is False, also delete the work branch.
    """
    _run_git(["checkout", ctx.original_branch], cwd=ctx.repo_path)
    if not keep_branch:
        _run_git(["branch", "-D", ctx.branch_name], cwd=ctx.repo_path)


def get_branch_diff(repo_path: str, branch_name: str, base_branch: str) -> str:
    """Get the diff between a work branch and the base branch."""
    result = _run_git(
        ["diff", f"{base_branch}...{branch_name}"],
        cwd=repo_path,
    )
    return result.stdout


def get_branch_log(repo_path: str, branch_name: str, base_branch: str) -> str:
    """Get commit log for a work branch since it diverged from base."""
    result = _run_git(
        ["log", "--oneline", f"{base_branch}..{branch_name}"],
        cwd=repo_path,
    )
    return result.stdout


def merge_branch(repo_path: str, branch_name: str, target_branch: str) -> None:
    """Merge a work branch into the target branch."""
    current = get_current_branch(repo_path)
    try:
        _run_git(["checkout", target_branch], cwd=repo_path)
        _run_git(["merge", "--no-ff", branch_name, "-m",
                  f"Merge wise-magpie work: {branch_name}"], cwd=repo_path)
    except subprocess.CalledProcessError:
        # Try to restore state on failure
        _run_git(["merge", "--abort"], cwd=repo_path)
        _run_git(["checkout", current], cwd=repo_path)
        raise


def delete_branch(repo_path: str, branch_name: str) -> None:
    """Delete a work branch."""
    _run_git(["branch", "-D", branch_name], cwd=repo_path)
