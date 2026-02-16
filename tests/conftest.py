"""Shared test fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from wise_magpie import config, db


@pytest.fixture(autouse=True)
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect config/data directory to a temp dir for every test."""
    cfg_dir = tmp_path / "wise-magpie-test"
    cfg_dir.mkdir()
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", cfg_dir / "config.toml")
    db.init_db()
    return cfg_dir
