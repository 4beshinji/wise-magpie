"""Tests for quota/claude_api.py — Anthropic OAuth usage endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from wise_magpie.quota.claude_api import UsageSnapshot, _parse_dt, fetch_usage


class TestParseDt:
    def test_valid_iso(self):
        dt = _parse_dt("2026-02-18T16:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_none_input(self):
        assert _parse_dt(None) is None

    def test_invalid_string(self):
        assert _parse_dt("not-a-date") is None


class TestFetchUsage:
    def _make_response(self, body: bytes, status: int = 200):
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_returns_none_when_no_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setattr("wise_magpie.quota.claude_api._CREDENTIALS_FILE", tmp_path / "missing.json")
        assert fetch_usage() is None

    def test_returns_none_when_credentials_malformed(self, tmp_path, monkeypatch):
        bad = tmp_path / ".credentials.json"
        bad.write_text("not json")
        monkeypatch.setattr("wise_magpie.quota.claude_api._CREDENTIALS_FILE", bad)
        assert fetch_usage() is None

    def test_returns_none_on_network_error(self, tmp_path, monkeypatch):
        import urllib.error
        creds = tmp_path / ".credentials.json"
        creds.write_text('{"claudeAiOauth": {"accessToken": "tok"}}')
        monkeypatch.setattr("wise_magpie.quota.claude_api._CREDENTIALS_FILE", creds)

        with patch("wise_magpie.quota.claude_api.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("timeout")):
            assert fetch_usage() is None

    def test_parses_full_response(self, tmp_path, monkeypatch):
        creds = tmp_path / ".credentials.json"
        creds.write_text('{"claudeAiOauth": {"accessToken": "tok"}}')
        monkeypatch.setattr("wise_magpie.quota.claude_api._CREDENTIALS_FILE", creds)

        import json
        payload = json.dumps({
            "five_hour": {"utilization": 16.0, "resets_at": "2026-02-18T16:00:00+00:00"},
            "seven_day": {"utilization": 28.0, "resets_at": "2026-02-23T04:00:00+00:00"},
            "seven_day_sonnet": {"utilization": 4.0, "resets_at": "2026-02-23T05:00:00+00:00"},
            "seven_day_oauth_apps": None,
            "seven_day_opus": None,
            "extra_usage": {"is_enabled": False},
        }).encode()

        with patch("wise_magpie.quota.claude_api.urllib.request.urlopen",
                   return_value=self._make_response(payload)):
            result = fetch_usage()

        assert result is not None
        assert result["five_hour_pct"] == 16.0
        assert result["week_all_pct"] == 28.0
        assert result["week_sonnet_pct"] == 4.0
        assert result["five_hour_resets_at"] is not None

    def test_handles_null_weekly_fields(self, tmp_path, monkeypatch):
        creds = tmp_path / ".credentials.json"
        creds.write_text('{"claudeAiOauth": {"accessToken": "tok"}}')
        monkeypatch.setattr("wise_magpie.quota.claude_api._CREDENTIALS_FILE", creds)

        import json
        payload = json.dumps({
            "five_hour": {"utilization": 10.0, "resets_at": None},
            "seven_day": None,
            "seven_day_sonnet": None,
        }).encode()

        with patch("wise_magpie.quota.claude_api.urllib.request.urlopen",
                   return_value=self._make_response(payload)):
            result = fetch_usage()

        assert result is not None
        assert result["five_hour_pct"] == 10.0
        assert result["week_all_pct"] is None
        assert result["week_sonnet_pct"] is None
        assert result["five_hour_resets_at"] is None


class TestAutoSync:
    def test_auto_sync_applies_corrections(self, tmp_path, monkeypatch):
        from wise_magpie.quota.corrections import auto_sync
        from wise_magpie.quota.estimator import estimate_remaining
        from wise_magpie import constants

        snapshot: UsageSnapshot = {
            "five_hour_pct": 50.0,
            "week_all_pct": 30.0,
            "week_sonnet_pct": 5.0,
            "five_hour_resets_at": None,
        }

        # fetch_usage is imported inside auto_sync(), so patch at source module
        with patch("wise_magpie.quota.claude_api.fetch_usage", return_value=snapshot):
            result = auto_sync()

        assert result is True
        sonnet_id = constants.MODEL_ALIASES["sonnet"]
        est = estimate_remaining(model=sonnet_id)
        assert est["remaining"] <= est["estimated_limit"] // 2 + 1

    def test_auto_sync_returns_false_on_api_failure(self):
        from wise_magpie.quota.corrections import auto_sync
        with patch("wise_magpie.quota.claude_api.fetch_usage", return_value=None):
            assert auto_sync() is False
