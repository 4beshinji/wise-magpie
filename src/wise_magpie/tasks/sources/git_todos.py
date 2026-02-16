"""Scan git repositories for TODO/FIXME/HACK/XXX comments."""

from __future__ import annotations

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


def _git_tracked_files(path: str) -> list[str]:
    """Return list of tracked files via ``git ls-files``."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.splitlines() if f.strip()]


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
