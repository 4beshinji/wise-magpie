"""Read tasks from a queue file (``.wise-magpie-tasks`` or ``wise-magpie-tasks.md``)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from wise_magpie.models import Task, TaskSource

# Matches markdown-style unchecked task list items:  - [ ] Some task text
_TASK_LINE_RE = re.compile(r"^-\s*\[\s*\]\s+(.+)$")

_QUEUE_FILENAMES = (
    ".wise-magpie-tasks",
    "wise-magpie-tasks.md",
)


def _find_queue_file(path: str) -> Path | None:
    """Locate the first matching queue file in *path*."""
    root = Path(path).resolve()
    for name in _QUEUE_FILENAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def scan(path: str) -> list[Task]:
    """Parse a markdown task-list queue file under *path*.

    Lines that match ``- [ ] <text>`` are treated as tasks.  Returns a
    list of :class:`Task` objects with ``source=TaskSource.QUEUE_FILE``
    and ``source_ref`` set to ``"<filename>:<line-number>"``.
    """
    queue_file = _find_queue_file(path)
    if queue_file is None:
        return []

    tasks: list[Task] = []
    try:
        lines = queue_file.read_text(errors="replace").splitlines()
    except OSError:
        return []

    for lineno, line in enumerate(lines, start=1):
        match = _TASK_LINE_RE.match(line.strip())
        if match is None:
            continue
        title = match.group(1).strip()
        if not title:
            continue

        tasks.append(
            Task(
                title=title,
                description="",
                source=TaskSource.QUEUE_FILE,
                source_ref=f"{queue_file.name}:{lineno}",
                created_at=datetime.now(),
            )
        )

    return tasks
