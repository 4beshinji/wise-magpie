"""Auto-generate routine maintenance tasks based on configurable templates.

Each built-in template defines a trigger condition (time elapsed, git
activity, commit count, etc.).  When ``scan()`` is called the module checks
every enabled template and yields :class:`Task` objects for those whose
conditions are met.  Deduplication is handled by the caller via the
standard ``(source, source_ref)`` key — we set
``source_ref = "{task_type}:{YYYY-MM-DD}"`` so at most one task of each
type is created per day.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from wise_magpie import config, db
from wise_magpie.models import Task, TaskSource, TaskStatus


# ---------------------------------------------------------------------------
# Template dataclass
# ---------------------------------------------------------------------------

@dataclass
class AutoTaskTemplate:
    """Describes one kind of auto-generated task."""

    task_type: str
    title: str
    description: str
    # Condition parameters (not all apply to every template)
    interval_hours: int = 0
    min_commits: int = 0
    needs_code_changes: bool = False
    needs_new_commits: bool = False


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

BUILTIN_TEMPLATES: list[AutoTaskTemplate] = [
    AutoTaskTemplate(
        task_type="run_tests",
        title="Run test suite",
        description="Run the full test suite, investigate any failures, and fix broken tests.",
        interval_hours=24,
        needs_new_commits=True,
    ),
    AutoTaskTemplate(
        task_type="update_docs",
        title="Update documentation",
        description="Review recent code changes and update README or other documentation to stay in sync.",
        interval_hours=48,
        needs_code_changes=True,
    ),
    AutoTaskTemplate(
        task_type="clean_commits",
        title="Clean up commit history",
        description="Review the current branch commits, squash fixups, and improve commit messages.",
        min_commits=10,
    ),
    AutoTaskTemplate(
        task_type="lint_check",
        title="Run linter and fix issues",
        description="Run the project linter (ruff/flake8/eslint), auto-fix where possible, and address remaining warnings.",
        interval_hours=12,
        needs_code_changes=True,
    ),
    AutoTaskTemplate(
        task_type="dependency_check",
        title="Check dependency updates",
        description="Check for outdated dependencies and evaluate available upgrades for security and compatibility.",
        interval_hours=168,
    ),
    AutoTaskTemplate(
        task_type="security_audit",
        title="Audit code for security issues",
        description=(
            "Scan the codebase for security vulnerabilities: hardcoded secrets, "
            "SQL injection, XSS, command injection, insecure deserialization, "
            "and other OWASP Top 10 risks. Report findings and apply fixes."
        ),
        interval_hours=168,
        needs_code_changes=True,
    ),
    AutoTaskTemplate(
        task_type="test_coverage",
        title="Generate tests for uncovered code",
        description=(
            "Identify functions and branches with no test coverage. "
            "Generate unit tests for the most critical uncovered paths. "
            "Run the test suite to verify the new tests pass."
        ),
        interval_hours=48,
        needs_code_changes=True,
    ),
    AutoTaskTemplate(
        task_type="dead_code_detection",
        title="Detect and remove dead code",
        description=(
            "Find unused imports, functions, variables, and unreachable code. "
            "Remove dead code and verify the test suite still passes."
        ),
        interval_hours=168,
        needs_code_changes=True,
    ),
    AutoTaskTemplate(
        task_type="changelog_generation",
        title="Generate changelog from recent commits",
        description=(
            "Review recent commit history and generate or update CHANGELOG entries. "
            "Group changes by category (added, changed, fixed, removed) "
            "following Keep a Changelog format."
        ),
        min_commits=5,
    ),
    AutoTaskTemplate(
        task_type="deprecation_cleanup",
        title="Clean up deprecated code usage",
        description=(
            "Find usage of deprecated APIs, functions, and patterns in the codebase. "
            "Migrate to recommended alternatives and remove deprecation warnings."
        ),
        interval_hours=336,
        needs_code_changes=True,
    ),
    AutoTaskTemplate(
        task_type="type_coverage",
        title="Add type annotations to untyped code",
        description=(
            "Identify functions and methods missing type annotations. "
            "Add type hints for parameters and return values. "
            "Run the type checker to verify correctness."
        ),
        interval_hours=168,
        needs_code_changes=True,
    ),
    AutoTaskTemplate(
        task_type="pentest_checklist",
        title="Run penetration test checklist",
        description=(
            "Perform authorized penetration testing on the application. "
            "Check authentication and session management (brute-force protection, "
            "session fixation, insecure tokens). "
            "Test for insecure direct object references (IDOR) and privilege escalation. "
            "Fuzz API endpoints for unexpected inputs and error disclosure. "
            "Review access controls and verify least-privilege enforcement. "
            "Run automated scanners where applicable (bandit, semgrep, OWASP ZAP). "
            "Document each finding with severity (Critical/High/Medium/Low) and remediation steps."
        ),
        interval_hours=720,
        needs_code_changes=True,
    ),
]


def _template_map() -> dict[str, AutoTaskTemplate]:
    return {t.task_type: t for t in BUILTIN_TEMPLATES}


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _has_commits_since(path: str, since: datetime) -> bool:
    """Return True if the repo at *path* has commits after *since*."""
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    result = subprocess.run(
        ["git", "log", "--oneline", f"--since={since_str}", "-1"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _has_code_changes_since(path: str, since: datetime) -> bool:
    """Return True if tracked files changed since *since*."""
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    result = subprocess.run(
        ["git", "log", "--oneline", "--diff-filter=ACMR", f"--since={since_str}", "-1"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _branch_commit_count(path: str) -> int:
    """Return the number of commits on the current branch ahead of main/master."""
    for base in ("main", "master"):
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{base}..HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            try:
                return int(result.stdout.strip())
            except ValueError:
                continue
    return 0


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def _last_completed_at(task_type: str) -> datetime | None:
    """Return the most recent ``completed_at`` for a completed auto_task of this type."""
    all_tasks = db.get_tasks_by_status(TaskStatus.COMPLETED)
    matches = [
        t
        for t in all_tasks
        if t.source == TaskSource.AUTO_TASK
        and t.source_ref.startswith(f"{task_type}:")
        and t.completed_at is not None
    ]
    if not matches:
        return None
    return max(t.completed_at for t in matches)  # type: ignore[arg-type]


def _interval_elapsed(task_type: str, interval_hours: int) -> bool:
    """Return True if *interval_hours* have passed since the last completed task of this type."""
    last = _last_completed_at(task_type)
    if last is None:
        return True  # never completed → eligible
    return datetime.now() - last >= timedelta(hours=interval_hours)


def _check_template(
    template: AutoTaskTemplate,
    path: str,
    cfg: dict[str, Any],
) -> bool:
    """Evaluate whether *template*'s trigger conditions are all met."""
    task_cfg = cfg.get(template.task_type, {})
    if not task_cfg.get("enabled", True):
        return False

    interval = task_cfg.get("interval_hours", template.interval_hours)

    # Time-based check
    if interval > 0 and not _interval_elapsed(template.task_type, interval):
        return False

    # Commit-count check (clean_commits)
    if template.min_commits > 0:
        threshold = task_cfg.get("min_commits", template.min_commits)
        if _branch_commit_count(path) < threshold:
            return False

    # Compute the "since" reference for git checks
    since = datetime.now() - timedelta(hours=interval) if interval > 0 else None

    # Git activity checks
    if template.needs_new_commits and since is not None:
        if not _has_commits_since(path, since):
            return False

    if template.needs_code_changes and since is not None:
        if not _has_code_changes_since(path, since):
            return False

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan(path: str) -> list[Task]:
    """Check all enabled auto-task templates and return tasks whose conditions are met.

    Each returned task has ``source=TaskSource.AUTO_TASK`` and
    ``source_ref="{task_type}:{YYYY-MM-DD}"``.  The caller's dedup logic
    (matching on ``(source, source_ref)``) ensures only one task per type
    per day is created.
    """
    cfg = config.load_config().get("auto_tasks", {})
    if not cfg.get("enabled", False):
        return []

    work_dir = cfg.get("work_dir", path) or path
    today = date.today().isoformat()
    templates = _template_map()

    tasks: list[Task] = []
    for template in templates.values():
        if not _check_template(template, work_dir, cfg):
            continue

        tasks.append(
            Task(
                title=template.title,
                description=template.description,
                source=TaskSource.AUTO_TASK,
                source_ref=f"{template.task_type}:{today}",
                created_at=datetime.now(),
            )
        )

    return tasks
