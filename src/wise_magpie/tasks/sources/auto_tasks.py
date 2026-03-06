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

import json
import logging
import os
import re as _re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from wise_magpie import config, db
from wise_magpie.models import Task, TaskSource, TaskStatus

logger = logging.getLogger("wise-magpie")


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
        task_type="doc_sync_audit",
        title="Audit documentation against implementation",
        description=(
            "Scan all documentation files (README, docs/, docstrings, inline comments, "
            "CLI --help text, config examples) and compare them against the current "
            "implementation. Identify outdated instructions, incorrect examples, "
            "missing descriptions for new features, stale API references, and "
            "wrong default values. Fix every discrepancy found so that the "
            "documentation accurately reflects the code as it exists today."
        ),
        interval_hours=72,
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


def _get_head_hash(path: str) -> str | None:
    """Return the current HEAD commit hash, or None if not a git repo."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _get_diffstat(path: str, since_commit: str) -> tuple[int, int]:
    """Return (files_changed, total_lines_changed) between *since_commit* and HEAD."""
    result = subprocess.run(
        ["git", "diff", "--shortstat", since_commit, "HEAD"],
        cwd=path, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return 0, 0
    text = result.stdout
    files = 0
    lines = 0
    m = _re.search(r"(\d+) files? changed", text)
    if m:
        files = int(m.group(1))
    m = _re.search(r"(\d+) insertions?", text)
    if m:
        lines += int(m.group(1))
    m = _re.search(r"(\d+) deletions?", text)
    if m:
        lines += int(m.group(1))
    return files, lines


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
# Cron helpers
# ---------------------------------------------------------------------------

def _parse_cron_simple(cron_expr: str, ref: datetime) -> datetime | None:
    """Return the most recent fire time at or before *ref* for a basic cron expression.

    Supports the standard 5-field format: ``"minute hour day month weekday"``
    where ``*`` means "any".  Only simple integer values and ``*`` wildcards
    are handled; step/range syntax is not supported.

    Weekday convention: 0 = Monday … 6 = Sunday (Python's ``weekday()``).
    The common ``0 = Sunday`` convention is also recognised when the value
    is 7 or when parsing results in no match with the default convention.

    Returns ``None`` if the expression cannot be parsed or no recent fire
    time can be determined within a reasonable look-back window.
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return None

    def _field(s: str) -> int | None:
        if s == "*":
            return None
        try:
            return int(s)
        except ValueError:
            return None

    f_min, f_hour, f_day, f_month, f_wday = [_field(p) for p in parts]

    # Normalise weekday: cron 0/7 = Sunday → Python weekday 6
    if f_wday is not None:
        if f_wday == 0 or f_wday == 7:
            f_wday = 6  # Sunday in Python
        else:
            f_wday = f_wday - 1  # 1(Mon)→0 … 6(Sat)→5

    # Walk backwards minute-by-minute up to ~8 days to find the last firing.
    # We cap at 60*24*8 = 11 520 iterations which is cheap enough.
    candidate = ref.replace(second=0, microsecond=0)
    for _ in range(11_520):
        match = True
        if f_min is not None and candidate.minute != f_min:
            match = False
        if match and f_hour is not None and candidate.hour != f_hour:
            match = False
        if match and f_day is not None and candidate.day != f_day:
            match = False
        if match and f_month is not None and candidate.month != f_month:
            match = False
        if match and f_wday is not None and candidate.weekday() != f_wday:
            match = False
        if match:
            return candidate
        candidate -= timedelta(minutes=1)

    return None


def _cron_triggered(cron_expr: str, last_completed: datetime | None) -> bool:
    """Return True if the cron schedule has fired since *last_completed*.

    Uses ``croniter`` when available; falls back to :func:`_parse_cron_simple`
    for basic expressions using only the standard library.

    Args:
        cron_expr: A 5-field cron expression, e.g. ``"0 9 * * 1"``.
        last_completed: The last time a task of this type completed, or
            ``None`` if it has never completed.

    Returns:
        ``True`` when the schedule has produced at least one fire time
        after *last_completed* (or when *last_completed* is ``None``).
    """
    if last_completed is None:
        return True

    now = datetime.now()

    # Try croniter first (optional dependency).
    try:
        from croniter import croniter  # type: ignore[import]
        # get_prev returns the most recent fire time <= now
        itr = croniter(cron_expr, now)
        last_fire = itr.get_prev(datetime)
        return last_fire > last_completed
    except ImportError:
        pass

    # Fall back to simple parser.
    last_fire = _parse_cron_simple(cron_expr, now)
    if last_fire is None:
        # Cannot parse — do not trigger to avoid false positives.
        return False
    return last_fire > last_completed


# ---------------------------------------------------------------------------
# Cooling reset — detect large changes and bypass interval gates
# ---------------------------------------------------------------------------

COOLING_STATE_FILE = "cooling_state.json"

# Default thresholds (overridable via [auto_tasks] config)
DEFAULT_COOLING_RESET_FILES = 10
DEFAULT_COOLING_RESET_LINES = 200


def _cooling_state_path():
    return config.data_dir() / COOLING_STATE_FILE


def _load_cooling_state() -> dict:
    p = _cooling_state_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cooling_state(state: dict) -> None:
    try:
        _cooling_state_path().write_text(json.dumps(state, indent=2))
    except OSError:
        pass


def check_cooling_reset(path: str, cfg: dict[str, Any]) -> bool:
    """Detect large code changes since last check and reset cooling if exceeded.

    Compares current HEAD against the stored last-seen commit hash for *path*.
    If the diff exceeds ``cooling_reset_files`` or ``cooling_reset_lines``
    thresholds, records a cooling-reset timestamp for this repo.

    Returns True if cooling was reset (large changes detected).
    """
    threshold_files = cfg.get("cooling_reset_files", DEFAULT_COOLING_RESET_FILES)
    threshold_lines = cfg.get("cooling_reset_lines", DEFAULT_COOLING_RESET_LINES)

    repo_key = os.path.realpath(path)
    state = _load_cooling_state()
    repo = state.get(repo_key, {})

    head = _get_head_hash(path)
    if not head:
        return False

    last_head = repo.get("last_head")
    if not last_head or last_head == head:
        # First time or no new commits — just record state
        repo["last_head"] = head
        state[repo_key] = repo
        _save_cooling_state(state)
        return False

    files_changed, lines_changed = _get_diffstat(path, last_head)
    is_large = files_changed >= threshold_files or lines_changed >= threshold_lines

    repo["last_head"] = head
    if is_large:
        repo["reset_at"] = datetime.now().isoformat()
        repo["trigger"] = {"files": files_changed, "lines": lines_changed}
        logger.info(
            "Cooling reset for %s: %d files, %d lines changed",
            path, files_changed, lines_changed,
        )
    state[repo_key] = repo
    _save_cooling_state(state)
    return is_large


def get_cooling_reset_at(path: str) -> datetime | None:
    """Return the most recent cooling-reset timestamp for *path*, or None."""
    state = _load_cooling_state()
    repo = state.get(os.path.realpath(path), {})
    ts = repo.get("reset_at")
    return datetime.fromisoformat(ts) if ts else None


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
    *,
    burst: bool = False,
    cooling_reset: datetime | None = None,
) -> bool:
    """Evaluate whether *template*'s trigger conditions are all met.

    Time-based triggering supports two mechanisms that can be combined with
    OR logic:

    * ``interval_hours`` — fire when at least this many hours have elapsed
      since the last completed task of this type (original behaviour).
    * ``cron`` — fire when the cron schedule has produced a fire time after
      the last completed task (new behaviour).

    When both are configured, the template fires if *either* condition is
    satisfied.  When neither is configured the time-based check is skipped.

    When *burst* is True, all time-based checks (interval, cron, git activity)
    are skipped — every enabled template fires unconditionally.

    When *cooling_reset* is set and is more recent than the last completed
    task of this type, all time-based and git-activity gates are bypassed
    (large code change detected → re-run everything).
    """
    task_cfg = cfg.get(template.task_type, {})
    if not task_cfg.get("enabled", True):
        return False

    # Burst mode: skip all interval / cron / git-activity gates
    if burst:
        return True

    # Cooling reset: large changes detected after last completion → fire
    if cooling_reset is not None:
        last = _last_completed_at(template.task_type)
        if last is None or cooling_reset > last:
            return True

    interval = task_cfg.get("interval_hours", template.interval_hours)
    cron_expr: str = task_cfg.get("cron", "")

    # Time-based check (interval OR cron, skipped when neither is set)
    if interval > 0 or cron_expr:
        interval_ok = interval > 0 and _interval_elapsed(template.task_type, interval)
        cron_ok = bool(cron_expr) and _cron_triggered(
            cron_expr, _last_completed_at(template.task_type)
        )
        if not (interval_ok or cron_ok):
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

def _scan_one(path: str, cfg: dict, prefix: str = "", *, burst: bool = False) -> list[Task]:
    """Scan a single directory and return auto-tasks whose conditions are met."""
    # Detect large changes and obtain cooling-reset timestamp for this repo
    check_cooling_reset(path, cfg)
    cooling_reset = get_cooling_reset_at(path)

    today = date.today().isoformat()
    templates = _template_map()
    tasks: list[Task] = []
    for template in templates.values():
        if not _check_template(template, path, cfg, burst=burst, cooling_reset=cooling_reset):
            continue
        title = f"[{prefix}] {template.title}" if prefix else template.title
        source_ref = f"{template.task_type}:{today}" if not prefix else f"{template.task_type}:{prefix}:{today}"
        tasks.append(
            Task(
                title=title,
                description=template.description,
                source=TaskSource.AUTO_TASK,
                source_ref=source_ref,
                work_dir=path,
                created_at=datetime.now(),
            )
        )
    return tasks


def _discover_git_repos(parent: str) -> list[str]:
    """Return immediate subdirectories of *parent* that are git repositories."""
    import os
    from pathlib import Path as _Path
    repos = []
    try:
        for entry in sorted(os.scandir(parent), key=lambda e: e.name):
            if entry.is_dir() and (_Path(entry.path) / ".git").exists():
                repos.append(entry.path)
    except OSError:
        pass
    return repos


def scan(path: str) -> list[Task]:
    """Check all enabled auto-task templates and return tasks whose conditions are met.

    Supports multiple target directories via ``work_dirs`` or auto-discovery
    via ``work_dir_parent`` in config.
    Each returned task has ``source=TaskSource.AUTO_TASK`` and
    ``source_ref="{task_type}:{YYYY-MM-DD}"``.  The caller's dedup logic
    (matching on ``(source, source_ref)``) ensures only one task per type
    per day is created.

    In burst mode, all interval/cron/git-activity gates are bypassed so
    every enabled template fires for every target directory.
    """
    full_cfg = config.load_config()
    cfg = full_cfg.get("auto_tasks", {})
    if not cfg.get("enabled", False):
        return []

    burst = full_cfg.get("daemon", {}).get("burst_mode", False)

    # Collect target directories from all sources (merged, deduplicated).
    work_dirs: list[str] = []
    seen: set[str] = set()

    def _add(d: str) -> None:
        if d not in seen:
            seen.add(d)
            work_dirs.append(d)

    # 1. work_dir_parent: string or list of strings → auto-discover git repos
    parent = cfg.get("work_dir_parent", "")
    if parent:
        from pathlib import Path as _Path
        parents = parent if isinstance(parent, list) else [parent]
        for p in parents:
            if p:
                for repo in _discover_git_repos(str(_Path(p).expanduser())):
                    _add(repo)

    # 2. work_dirs: explicit list (merged, not overridden)
    for d in cfg.get("work_dirs", []):
        _add(d)

    # 3. Fallback to work_dir / path if nothing collected
    if not work_dirs:
        single = cfg.get("work_dir", path) or path
        _add(single)

    tasks: list[Task] = []
    if len(work_dirs) == 1:
        tasks.extend(_scan_one(work_dirs[0], cfg, prefix="", burst=burst))
    else:
        import os
        for wd in work_dirs:
            prefix = os.path.basename(wd.rstrip("/"))
            tasks.extend(_scan_one(wd, cfg, prefix=prefix, burst=burst))

    return tasks
