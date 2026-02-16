"""TOML configuration management."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from wise_magpie import constants

CONFIG_DIR = Path(os.environ.get("WISE_MAGPIE_CONFIG_DIR", "~/.config/wise-magpie")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_CONFIG = """\
# wise-magpie configuration

[quota]
# Quota window duration in hours
window_hours = {window_hours}
# Estimated messages per window
messages_per_window = {messages_per_window}
# Reserve this fraction of quota for interactive use
safety_margin = {safety_margin}

[budget]
# Maximum USD per autonomous task
max_task_usd = {max_task_usd}
# Maximum USD per day for autonomous execution
max_daily_usd = {max_daily_usd}

[activity]
# Minutes of inactivity before considered idle
idle_threshold_minutes = {idle_threshold_minutes}
# Stop starting new tasks this many minutes before predicted return
return_buffer_minutes = {return_buffer_minutes}

[daemon]
# Seconds between daemon poll cycles
poll_interval = {poll_interval}

[claude]
# Model to use for autonomous tasks
model = "{model}"
# Additional claude CLI flags
extra_flags = []
""".format(
    window_hours=constants.DEFAULT_QUOTA_WINDOW_HOURS,
    messages_per_window=constants.DEFAULT_MESSAGES_PER_WINDOW,
    safety_margin=constants.QUOTA_SAFETY_MARGIN,
    max_task_usd=constants.MAX_TASK_BUDGET_USD,
    max_daily_usd=constants.MAX_DAILY_AUTONOMOUS_USD,
    idle_threshold_minutes=constants.IDLE_THRESHOLD_MINUTES,
    return_buffer_minutes=constants.RETURN_BUFFER_MINUTES,
    poll_interval=constants.POLL_INTERVAL_SECONDS,
    model=constants.DEFAULT_MODEL,
)


def init_config(force: bool = False) -> Path:
    """Create default config file. Returns path to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists() and not force:
        raise FileExistsError(f"Config already exists: {CONFIG_FILE}")
    CONFIG_FILE.write_text(DEFAULT_CONFIG)
    return CONFIG_FILE


def load_config() -> dict[str, Any]:
    """Load config from TOML file, falling back to defaults."""
    if CONFIG_FILE.exists():
        return tomllib.loads(CONFIG_FILE.read_text())
    return tomllib.loads(DEFAULT_CONFIG)


def get(section: str, key: str, default: Any = None) -> Any:
    """Get a config value by section and key."""
    cfg = load_config()
    return cfg.get(section, {}).get(key, default)


def data_dir() -> Path:
    """Return the data directory (same as config dir for simplicity)."""
    d = CONFIG_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d
