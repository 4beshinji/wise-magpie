"""Tests for config management."""

from wise_magpie import config


def test_init_config(tmp_config_dir):
    path = config.init_config()
    assert path.exists()
    content = path.read_text()
    assert "[quota]" in content
    assert "[budget]" in content
    assert "[claude]" in content


def test_init_config_already_exists(tmp_config_dir):
    config.init_config()
    import pytest
    with pytest.raises(FileExistsError):
        config.init_config()


def test_init_config_force(tmp_config_dir):
    config.init_config()
    # Should not raise
    config.init_config(force=True)


def test_load_config_defaults():
    cfg = config.load_config()
    assert cfg["quota"]["window_hours"] == 5
    assert cfg["budget"]["max_task_usd"] == 2.0
    assert cfg["claude"]["model"] == "claude-sonnet-4-5-20250929"


def test_get():
    val = config.get("quota", "window_hours", 10)
    assert val == 5


def test_get_missing_key():
    val = config.get("nonexistent", "key", "default")
    assert val == "default"
