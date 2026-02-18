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


def test_load_config_merges_defaults_for_missing_section(tmp_config_dir):
    """On-disk config missing [auto_tasks] should still expose defaults."""
    # Write a minimal config without [auto_tasks]
    (tmp_config_dir / "config.toml").write_text(
        "[quota]\nwindow_hours = 5\n"
    )
    cfg = config.load_config()
    # auto_tasks section must come from defaults (enabled = false)
    assert "auto_tasks" in cfg
    assert cfg["auto_tasks"]["enabled"] is False


def test_load_config_on_disk_overrides_default(tmp_config_dir):
    """Values present in the on-disk config override the defaults."""
    (tmp_config_dir / "config.toml").write_text(
        "[quota]\nwindow_hours = 99\n"
    )
    cfg = config.load_config()
    assert cfg["quota"]["window_hours"] == 99
    # Other default keys are still present
    assert "safety_margin" in cfg["quota"]


def test_deep_merge():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 99, "z": 0}, "c": 4}
    result = config._deep_merge(base, override)
    assert result == {"a": {"x": 1, "y": 99, "z": 0}, "b": 3, "c": 4}
