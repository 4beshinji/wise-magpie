"""Task priority scoring."""

from __future__ import annotations

import re

from wise_magpie import db
from wise_magpie.models import Task, TaskSource, TaskStatus

# --- Source weights (0-100 contribution) ---
_SOURCE_WEIGHT: dict[TaskSource, float] = {
    TaskSource.MANUAL: 40.0,
    TaskSource.QUEUE_FILE: 35.0,
    TaskSource.ISSUE: 30.0,
    TaskSource.GIT_TODO: 20.0,
    TaskSource.MARKDOWN: 15.0,
}

# --- Keyword boosts applied to the title + description ---
# Each tuple is (pattern, additive bonus).
_KEYWORD_RULES: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\b(bug|fix|crash|error|broken)\b", re.IGNORECASE), 25.0),
    (re.compile(r"\b(security|vulnerability|vuln|cve)\b", re.IGNORECASE), 30.0),
    (re.compile(r"\b(refactor|cleanup|clean[- ]?up)\b", re.IGNORECASE), 10.0),
    (re.compile(r"\b(doc|docs|documentation|readme)\b", re.IGNORECASE), 5.0),
    (re.compile(r"\b(test|tests|testing)\b", re.IGNORECASE), 8.0),
    (re.compile(r"\b(perf|performance|slow)\b", re.IGNORECASE), 15.0),
    (re.compile(r"\bFIXME\b"), 20.0),
    (re.compile(r"\bHACK\b"), 15.0),
    (re.compile(r"\bXXX\b"), 15.0),
]

# --- Complexity heuristic ---
# Shorter descriptions are treated as simpler tasks, which are better
# candidates for autonomous execution and thus get a small priority boost.
_MAX_COMPLEXITY_BONUS = 15.0
_COMPLEXITY_CHAR_THRESHOLD = 200  # descriptions longer than this get no bonus


def calculate_priority(task: Task) -> float:
    """Return a priority score in the range 0--100 for *task*.

    The score is the sum of three components (clamped to [0, 100]):

    1. **Source weight** -- manual tasks score highest, scanned TODOs lower.
    2. **Keyword boost** -- presence of important keywords in the title or
       description raises priority.
    3. **Complexity bonus** -- shorter (presumably simpler) tasks get a small
       bonus because they are easier to handle autonomously.
    """
    score = _SOURCE_WEIGHT.get(task.source, 10.0)

    text = f"{task.title} {task.description}"
    for pattern, bonus in _KEYWORD_RULES:
        if pattern.search(text):
            score += bonus

    desc_len = len(task.description) + len(task.title)
    if desc_len < _COMPLEXITY_CHAR_THRESHOLD:
        ratio = 1.0 - (desc_len / _COMPLEXITY_CHAR_THRESHOLD)
        score += _MAX_COMPLEXITY_BONUS * ratio

    return max(0.0, min(100.0, score))


def reprioritize_all() -> None:
    """Recalculate priorities for every pending task in the database."""
    db.init_db()
    tasks = db.get_tasks_by_status(TaskStatus.PENDING)
    for task in tasks:
        task.priority = calculate_priority(task)
        db.update_task(task)
