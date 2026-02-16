"""Default constants for quota limits and model costs."""

from __future__ import annotations

# Claude Max $200 plan quota defaults (per 5-hour window)
DEFAULT_QUOTA_WINDOW_HOURS = 5
DEFAULT_MESSAGES_PER_WINDOW = 225  # approximate

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

# Safety margins
QUOTA_SAFETY_MARGIN = 0.15  # Reserve 15% of quota for user
MAX_TASK_BUDGET_USD = 2.00  # Default per-task budget limit
MAX_DAILY_AUTONOMOUS_USD = 10.00  # Daily autonomous spending limit

# Activity detection
IDLE_THRESHOLD_MINUTES = 30  # Minutes of no activity before considered idle
RETURN_BUFFER_MINUTES = 15  # Stop new tasks this many minutes before predicted return

# Daemon
POLL_INTERVAL_SECONDS = 60  # How often daemon checks for work
PID_FILE_NAME = "wise-magpie.pid"
LOG_FILE_NAME = "wise-magpie.log"

# Database
DB_FILE_NAME = "wise-magpie.db"
