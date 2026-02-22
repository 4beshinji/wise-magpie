"""Default constants for quota limits and model costs."""

from __future__ import annotations

# Claude Max $200 plan quota defaults (per 5-hour window)
DEFAULT_QUOTA_WINDOW_HOURS = 5
DEFAULT_MESSAGES_PER_WINDOW = 225  # deprecated: use MODEL_QUOTAS / config [quota.limits]

# Model aliases (short names usable in config and CLI)
MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
}

# Per-model messages per 5h window (estimates, overridable via config [quota.limits])
MODEL_QUOTAS: dict[str, int] = {
    "claude-opus-4-6": 50,
    "claude-sonnet-4-5-20250929": 225,
    "claude-haiku-4-5-20251001": 1000,
}

# Cost estimates per model (USD per 1M tokens)
MODEL_COSTS = {
    "claude-sonnet-4-5-20250929": {
        "input": 3.00,
        "output": 15.00,
    },
    "claude-opus-4-6": {
        "input": 15.00,
        "output": 75.00,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
    },
}

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


def resolve_model(name: str) -> str:
    """Resolve an alias or full model ID to a full model ID."""
    return MODEL_ALIASES.get(name, name)

# Safety margins
QUOTA_SAFETY_MARGIN = 0.15  # Reserve 15% of quota for user
MAX_TASK_BUDGET_USD = 2.00  # Default per-task budget limit
MAX_DAILY_AUTONOMOUS_USD = 10.00  # Daily autonomous spending limit

# Activity detection
IDLE_THRESHOLD_MINUTES = 30  # Minutes of no activity before considered idle
RETURN_BUFFER_MINUTES = 15  # Stop new tasks this many minutes before predicted return

# Daemon
POLL_INTERVAL_SECONDS = 60  # How often daemon checks for work
MAX_PARALLEL_TASKS = 30          # Hard upper bound on concurrent autonomous tasks

# Weekly quota budget
WEEKLY_QUOTA_TARGET_PCT = 90.0   # Target max weekly usage % at reset time
WEEKLY_RESET_DAY = 0             # Day weekly quota resets (0=Mon … 6=Sun, UTC)
WEEKLY_RESET_HOUR = 0            # Hour (UTC) at which weekly quota resets
WEEKLY_INITIAL_PARALLEL_LIMIT = 10  # Limit before two measurements exist to compute rate
QUOTA_AUTO_SYNC_INTERVAL_MINUTES = 30  # How often daemon syncs quota from Anthropic API
PID_FILE_NAME = "wise-magpie.pid"
LOG_FILE_NAME = "wise-magpie.log"

# Database
DB_FILE_NAME = "wise-magpie.db"
