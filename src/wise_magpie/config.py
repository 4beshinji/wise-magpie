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
# Reserve this fraction of quota for interactive use
safety_margin = {safety_margin}

# Per-model message limits per window (check Claude UI and adjust)
[quota.limits]
opus = {quota_opus}
sonnet = {quota_sonnet}
haiku = {quota_haiku}

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
# Minutes between automatic quota syncs from Anthropic API (0 = disabled)
auto_sync_interval_minutes = {auto_sync_interval_minutes}

[claude]
# Fallback model for autonomous tasks (alias or full ID)
model = "{model}"
# Automatically select model based on task difficulty (default: true)
auto_select_model = true
# Additional claude CLI flags
extra_flags = []

[auto_tasks]
# Automatically generate routine maintenance tasks during scan
enabled = false
work_dir = "."

[auto_tasks.run_tests]
enabled = true
interval_hours = 24

[auto_tasks.update_docs]
enabled = true
interval_hours = 48

[auto_tasks.clean_commits]
enabled = true
min_commits = 10

[auto_tasks.lint_check]
enabled = true
interval_hours = 12

[auto_tasks.dependency_check]
enabled = true
interval_hours = 168

[auto_tasks.security_audit]
enabled = true
interval_hours = 168

[auto_tasks.test_coverage]
enabled = true
interval_hours = 48

[auto_tasks.dead_code_detection]
enabled = true
interval_hours = 168

[auto_tasks.changelog_generation]
enabled = true
min_commits = 5

[auto_tasks.deprecation_cleanup]
enabled = true
interval_hours = 336

[auto_tasks.type_coverage]
enabled = true
interval_hours = 168
""".format(
    window_hours=constants.DEFAULT_QUOTA_WINDOW_HOURS,
    safety_margin=constants.QUOTA_SAFETY_MARGIN,
    quota_opus=constants.MODEL_QUOTAS["claude-opus-4-6"],
    quota_sonnet=constants.MODEL_QUOTAS["claude-sonnet-4-5-20250929"],
    quota_haiku=constants.MODEL_QUOTAS["claude-haiku-4-5-20251001"],
    max_task_usd=constants.MAX_TASK_BUDGET_USD,
    max_daily_usd=constants.MAX_DAILY_AUTONOMOUS_USD,
    idle_threshold_minutes=constants.IDLE_THRESHOLD_MINUTES,
    return_buffer_minutes=constants.RETURN_BUFFER_MINUTES,
    poll_interval=constants.POLL_INTERVAL_SECONDS,
    model=constants.DEFAULT_MODEL,
    auto_sync_interval_minutes=constants.QUOTA_AUTO_SYNC_INTERVAL_MINUTES,
)


def init_config(force: bool = False) -> Path:
    """Create default config file. Returns path to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists() and not force:
        raise FileExistsError(f"Config already exists: {CONFIG_FILE}")
    CONFIG_FILE.write_text(DEFAULT_CONFIG)
    return CONFIG_FILE


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    """Load config from TOML file, merged on top of built-in defaults.

    Keys present in the default config but absent from the on-disk file
    (e.g. sections added in newer versions) are filled in automatically.
    """
    defaults = tomllib.loads(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        on_disk = tomllib.loads(CONFIG_FILE.read_text())
        return _deep_merge(defaults, on_disk)
    return defaults


def get(section: str, key: str, default: Any = None) -> Any:
    """Get a config value by section and key."""
    cfg = load_config()
    return cfg.get(section, {}).get(key, default)


def data_dir() -> Path:
    """Return the data directory (same as config dir for simplicity)."""
    d = CONFIG_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def set_value(section: str, key: str, value: Any) -> None:
    """Persist a single key inside *section* in the on-disk config file.

    If the key already exists it is updated in-place; if the section exists
    but the key is absent the key is appended to the section; if the section
    itself is absent both are appended at the end of the file.

    Only int, float, bool, and str values are supported (sufficient for all
    current use cases).
    """
    import re

    if isinstance(value, bool):
        val_str = "true" if value else "false"
    elif isinstance(value, str):
        val_str = f'"{value}"'
    else:
        val_str = str(value)

    section_header = f"[{section}]"

    if not CONFIG_FILE.exists():
        init_config()

    lines = CONFIG_FILE.read_text().splitlines(keepends=True)
    new_lines: list[str] = []
    in_section = False
    key_found = False
    key_pattern = re.compile(rf"^{re.escape(key)}\s*=")

    for line in lines:
        stripped = line.strip()
        if stripped == section_header:
            in_section = True
        elif stripped.startswith("[") and not stripped.startswith("[" + section + "]"):
            if in_section and not key_found:
                new_lines.append(f"{key} = {val_str}\n")
                key_found = True
            in_section = False

        if in_section and not key_found and key_pattern.match(stripped):
            new_lines.append(f"{key} = {val_str}\n")
            key_found = True
            continue  # discard original line

        new_lines.append(line)

    if not key_found:
        if in_section:
            new_lines.append(f"{key} = {val_str}\n")
        else:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            new_lines.append(f"\n{section_header}\n{key} = {val_str}\n")

    CONFIG_FILE.write_text("".join(new_lines))
