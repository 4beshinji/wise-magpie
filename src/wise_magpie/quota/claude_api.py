"""Fetch quota utilization from Anthropic's OAuth usage endpoint.

This module reads the same data that Claude Code's /usage command displays,
by calling the undocumented internal endpoint:

    GET https://api.anthropic.com/api/oauth/usage

The Bearer token is read from ~/.claude/.credentials.json which Claude Code
maintains automatically (including refresh).

NOTE: This endpoint is not officially documented and may change without notice.
All calls are wrapped in try/except so failures degrade gracefully.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict


_CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"
_USER_AGENT = "claude-code/2.1.45"


class UsageSnapshot(TypedDict):
    """Parsed usage percentages from the API."""
    five_hour_pct: float        # "Current session X%" in Claude's /usage
    week_all_pct: float | None  # "Current week (all models) X%"
    week_sonnet_pct: float | None  # "Current week (sonnet only) X%"
    five_hour_resets_at: datetime | None  # When the 5h window resets


def _read_token() -> str | None:
    """Read the OAuth access token from Claude Code's credentials file."""
    try:
        data = json.loads(_CREDENTIALS_FILE.read_text())
        return data.get("claudeAiOauth", {}).get("accessToken")
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def fetch_usage() -> UsageSnapshot | None:
    """Fetch current quota utilization from Anthropic's OAuth usage API.

    Returns a :class:`UsageSnapshot` on success, or ``None`` if the
    credentials file is missing, the token is invalid, or the request fails.
    """
    token = _read_token()
    if not token:
        return None

    req = urllib.request.Request(
        _USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": _BETA_HEADER,
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data: dict = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None

    five_hour = data.get("five_hour") or {}
    seven_day = data.get("seven_day") or {}
    seven_day_sonnet = data.get("seven_day_sonnet") or {}

    return UsageSnapshot(
        five_hour_pct=float(five_hour.get("utilization") or 0.0),
        week_all_pct=(
            float(seven_day["utilization"])
            if seven_day.get("utilization") is not None
            else None
        ),
        week_sonnet_pct=(
            float(seven_day_sonnet["utilization"])
            if seven_day_sonnet.get("utilization") is not None
            else None
        ),
        five_hour_resets_at=_parse_dt(five_hour.get("resets_at")),
    )
