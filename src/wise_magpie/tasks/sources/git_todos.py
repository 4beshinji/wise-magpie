"""Scan git repositories for TODO/FIXME/HACK/XXX comments."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from datetime import datetime
from pathlib import Path

from wise_magpie.models import Task, TaskSource

# Pattern matches common comment markers followed by TODO/FIXME/HACK/XXX
# Captures the keyword and the trailing text.
_TODO_RE = re.compile(
    r"(?:#|//|/\*|\*|--|;)\s*"           # comment leader
    r"(TODO|FIXME|HACK|XXX)"             # keyword
    r"[\s:(\-]*"                         # optional separator
    r"(.+?)$",                           # comment body
    re.IGNORECASE,
)

# Directory names that are considered test directories.
_TEST_DIRS: frozenset[str] = frozenset({"tests", "test", "spec", "__tests__"})

# Filename patterns that indicate test files.
_TEST_FILE_PATTERNS: tuple[str, ...] = (
    "test_*.py",
    "*_test.py",
    "*_spec.py",
    "conftest.py",
    "*.test.js",
    "*.test.ts",
    "*.spec.js",
    "*.spec.ts",
)


def _is_test_file(rel_path: str) -> bool:
    """Return True if *rel_path* is a test file that should be excluded."""
    parts = Path(rel_path).parts
    # Any parent directory component matches a test directory name
    if any(part in _TEST_DIRS for part in parts[:-1]):
        return True
    # Filename matches a test file pattern
    name = parts[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in _TEST_FILE_PATTERNS)


def _git_tracked_files(path: str) -> list[str]:
    """Return list of tracked non-test files via ``git ls-files``."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [
        f for f in result.stdout.splitlines()
        if f.strip() and not _is_test_file(f)
    ]


def scan(path: str) -> list[Task]:
    """Walk through tracked files in *path* and collect TODO-style comments.

    Returns a list of :class:`Task` objects with
    ``source=TaskSource.GIT_TODO`` and ``source_ref`` set to
    ``"<relative-file>:<line-number>"``.
    """
    root = Path(path).resolve()
    tracked = _git_tracked_files(str(root))

    tasks: list[Task] = []
    for rel_path in tracked:
        file_path = root / rel_path
        if not file_path.is_file():
            continue
        try:
            lines = file_path.read_text(errors="replace").splitlines()
        except OSError:
            continue

        for lineno, line in enumerate(lines, start=1):
            match = _TODO_RE.search(line)
            if match is None:
                continue
            keyword = match.group(1).upper()
            body = match.group(2).strip().rstrip("*/").strip()
            if not body:
                continue

            title = f"[{keyword}] {body}"

            tasks.append(
                Task(
                    title=title,
                    description="",
                    source=TaskSource.GIT_TODO,
                    source_ref=f"{rel_path}:{lineno}",
                    created_at=datetime.now(),
                )
            )

    return tasks
