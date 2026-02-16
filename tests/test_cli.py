"""Tests for CLI commands via Click testing."""

from click.testing import CliRunner

from wise_magpie.cli import main


def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "wise-magpie" in result.output


def test_config_init():
    runner = CliRunner()
    result = runner.invoke(main, ["config", "init"])
    assert result.exit_code == 0
    assert "Config created" in result.output


def test_config_show():
    runner = CliRunner()
    # Init first
    runner.invoke(main, ["config", "init"])
    result = runner.invoke(main, ["config", "show"])
    assert result.exit_code == 0
    assert "[quota]" in result.output


def test_quota_show():
    runner = CliRunner()
    result = runner.invoke(main, ["quota", "show"])
    assert result.exit_code == 0
    assert "Quota Status" in result.output


def test_quota_correct():
    runner = CliRunner()
    result = runner.invoke(main, ["quota", "correct", "150"])
    assert result.exit_code == 0
    assert "Correction applied" in result.output


def test_tasks_add_and_list():
    runner = CliRunner()
    result = runner.invoke(main, ["tasks", "add", "Test CLI task"])
    assert result.exit_code == 0
    assert "Added task" in result.output

    result = runner.invoke(main, ["tasks", "list"])
    assert result.exit_code == 0
    assert "Test CLI task" in result.output


def test_tasks_remove():
    runner = CliRunner()
    runner.invoke(main, ["tasks", "add", "To remove"])
    result = runner.invoke(main, ["tasks", "remove", "1"])
    assert result.exit_code == 0


def test_status():
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "Daemon:" in result.output


def test_schedule_show():
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "show"])
    assert result.exit_code == 0
    assert "Mon" in result.output


def test_schedule_predict():
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "predict"])
    assert result.exit_code == 0
    assert "Idle window predictions" in result.output


def test_review_list():
    runner = CliRunner()
    result = runner.invoke(main, ["review", "list"])
    assert result.exit_code == 0
