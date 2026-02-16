"""Difficulty-based model selection and quota-aware upgrade logic."""

from __future__ import annotations

import enum
import logging
from datetime import datetime, timedelta

from wise_magpie import config, constants
from wise_magpie.constants import MODEL_ALIASES, resolve_model
from wise_magpie.models import Task, TaskSource

logger = logging.getLogger("wise-magpie")


class TaskDifficulty(enum.Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


DIFFICULTY_MODEL_MAP: dict[TaskDifficulty, str] = {
    TaskDifficulty.SIMPLE: "claude-haiku-4-5-20251001",
    TaskDifficulty.MEDIUM: "claude-sonnet-4-5-20250929",
    TaskDifficulty.COMPLEX: "claude-opus-4-6",
}

# Model ordering for upgrade / downgrade
_MODEL_TIERS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-6",
]

COMPLEX_KEYWORDS = frozenset({
    "security", "vulnerability", "architecture", "migration",
    "performance", "critical", "concurrent", "race condition",
    "refactor", "redesign", "optimize", "scalab",
})

SIMPLE_KEYWORDS = frozenset({
    "docs", "documentation", "lint", "format", "typo",
    "clean", "todo", "comment", "rename", "update docs",
    "readme", "changelog", "license",
})


def assess_difficulty(task: Task) -> TaskDifficulty:
    """Assess task difficulty from title, description, and source."""
    text = (task.title + " " + task.description).lower()

    # Keyword matching
    complex_hits = sum(1 for kw in COMPLEX_KEYWORDS if kw in text)
    simple_hits = sum(1 for kw in SIMPLE_KEYWORDS if kw in text)

    # Source-based bias
    if task.source == TaskSource.AUTO_TASK:
        simple_hits += 1

    # Description length heuristic
    desc_len = len(task.description)
    if desc_len > 500:
        complex_hits += 1
    elif desc_len < 100:
        simple_hits += 1

    if complex_hits > simple_hits:
        return TaskDifficulty.COMPLEX
    if simple_hits > complex_hits:
        return TaskDifficulty.SIMPLE
    return TaskDifficulty.MEDIUM


def _upgrade_one_level(model: str) -> str:
    """Move one tier up: Haiku -> Sonnet -> Opus -> Opus."""
    try:
        idx = _MODEL_TIERS.index(model)
    except ValueError:
        return model
    return _MODEL_TIERS[min(idx + 1, len(_MODEL_TIERS) - 1)]


def _downgrade_one_level(model: str) -> str:
    """Move one tier down: Opus -> Sonnet -> Haiku -> Haiku."""
    try:
        idx = _MODEL_TIERS.index(model)
    except ValueError:
        return model
    return _MODEL_TIERS[max(idx - 1, 0)]


def _has_model_quota(model: str) -> bool:
    """Check if the given model has remaining quota."""
    from wise_magpie.quota.estimator import estimate_remaining

    info = estimate_remaining(model=model)
    return info["available_for_autonomous"] > 0


def should_upgrade_model() -> tuple[bool, str]:
    """Determine whether to upgrade the model based on quota situation.

    Returns (should_upgrade, reason).

    Conditions:
      1. Window remaining < 1.5h AND remaining quota > 30%
      2. Next predicted idle window > 6h within 8h AND remaining quota > 40%
    """
    from wise_magpie.quota.estimator import estimate_remaining

    info = estimate_remaining()
    now = datetime.now()
    window_end = info["window_end"]
    time_left = (window_end - now).total_seconds() / 3600.0
    remaining_pct = info["remaining_pct"]

    # Condition 1: window ending soon with surplus
    if time_left < 1.5 and remaining_pct > 30:
        return True, f"window ending in {time_left:.1f}h with {remaining_pct:.0f}% remaining"

    # Condition 2: long idle predicted with surplus
    if remaining_pct > 40:
        try:
            from wise_magpie.patterns.predictor import predict_idle_windows

            windows = predict_idle_windows(hours_ahead=8)
            long_idle = any(w["duration_hours"] >= 6 for w in windows)
            if long_idle:
                return True, f"long idle predicted with {remaining_pct:.0f}% remaining"
        except Exception:
            pass

    return False, ""


def select_model(task: Task) -> str:
    """Select the best model for a task. Main entry point.

    Logic:
      1. Auto-select disabled -> return configured default model
      2. Task has explicit model -> use it
      3. Assess difficulty -> map to model
      4. Check for upgrade opportunity
      5. Verify quota availability, downgrade if needed
    """
    cfg = config.load_config()

    if not cfg.get("claude", {}).get("auto_select_model", True):
        return resolve_model(cfg.get("claude", {}).get("model", constants.DEFAULT_MODEL))

    # Explicit model on task
    if task.model:
        return resolve_model(task.model)

    # Difficulty-based selection
    difficulty = assess_difficulty(task)
    target = DIFFICULTY_MODEL_MAP[difficulty]
    logger.debug(f"Task difficulty={difficulty.value}, base model={target}")

    # Upgrade check
    upgrade, reason = should_upgrade_model()
    if upgrade:
        original = target
        target = _upgrade_one_level(target)
        if target != original:
            logger.info(f"Upgrading {original} -> {target}: {reason}")

    # Quota check: downgrade if target model has no quota
    if not _has_model_quota(target):
        original = target
        target = _downgrade_one_level(target)
        logger.info(f"Downgrading {original} -> {target}: quota exhausted")

        # If still no quota, try one more level down
        if not _has_model_quota(target):
            target = _downgrade_one_level(target)
            logger.info(f"Further downgrade to {target}")

    return target
