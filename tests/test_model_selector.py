"""Tests for difficulty-based model selection."""

from datetime import datetime, timedelta
from unittest.mock import patch

from wise_magpie import constants, db
from wise_magpie.constants import resolve_model
from wise_magpie.models import Task, TaskSource
from wise_magpie.tasks.model_selector import (
    TaskDifficulty,
    _downgrade_one_level,
    _upgrade_one_level,
    assess_difficulty,
    select_model,
    should_upgrade_model,
)


# --- resolve_model ---

def test_resolve_model_alias():
    assert resolve_model("opus") == "claude-opus-4-6"
    assert resolve_model("sonnet") == "claude-sonnet-4-5-20250929"
    assert resolve_model("haiku") == "claude-haiku-4-5-20251001"


def test_resolve_model_full_id():
    assert resolve_model("claude-opus-4-6") == "claude-opus-4-6"


def test_resolve_model_unknown():
    assert resolve_model("unknown") == "unknown"


# --- assess_difficulty ---

def test_assess_difficulty_complex_keywords():
    task = Task(title="Fix security vulnerability", description="XSS in login form")
    assert assess_difficulty(task) == TaskDifficulty.COMPLEX


def test_assess_difficulty_simple_keywords():
    task = Task(title="Update documentation", description="Fix typo in README")
    assert assess_difficulty(task) == TaskDifficulty.SIMPLE


def test_assess_difficulty_medium_default():
    task = Task(
        title="Implement user profile page",
        description=(
            "Add profile editing with form validation and state management "
            "for the user settings. Include avatar upload and email change functionality."
        ),
    )
    assert assess_difficulty(task) == TaskDifficulty.MEDIUM


def test_assess_difficulty_auto_task_bias():
    task = Task(title="Run checks", source=TaskSource.AUTO_TASK)
    assert assess_difficulty(task) == TaskDifficulty.SIMPLE


def test_assess_difficulty_long_description_complex():
    task = Task(title="Implement feature", description="x " * 300)
    assert assess_difficulty(task) == TaskDifficulty.COMPLEX


def test_assess_difficulty_short_description_simple():
    task = Task(title="Fix bug", description="typo")
    assert assess_difficulty(task) == TaskDifficulty.SIMPLE


# --- upgrade / downgrade ---

def test_upgrade_one_level():
    assert _upgrade_one_level("claude-haiku-4-5-20251001") == "claude-sonnet-4-5-20250929"
    assert _upgrade_one_level("claude-sonnet-4-5-20250929") == "claude-opus-4-6"
    assert _upgrade_one_level("claude-opus-4-6") == "claude-opus-4-6"  # ceiling


def test_downgrade_one_level():
    assert _downgrade_one_level("claude-opus-4-6") == "claude-sonnet-4-5-20250929"
    assert _downgrade_one_level("claude-sonnet-4-5-20250929") == "claude-haiku-4-5-20251001"
    assert _downgrade_one_level("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"  # floor


def test_upgrade_unknown_model():
    assert _upgrade_one_level("unknown-model") == "unknown-model"


# --- should_upgrade_model ---

def test_should_upgrade_window_ending_soon():
    """Window ending in < 1.5h with > 30% remaining -> upgrade."""
    now = datetime.now()
    window_start = now - timedelta(hours=4)  # 1h left in 5h window
    info = {
        "window_start": window_start,
        "window_end": window_start + timedelta(hours=5),
        "remaining_pct": 50.0,
        "model": constants.DEFAULT_MODEL,
        "model_limit": 225,
        "estimated_limit": 225,
        "used": 112,
        "remaining": 113,
        "safety_reserved": 33,
        "available_for_autonomous": 80,
    }
    with patch("wise_magpie.quota.estimator.estimate_remaining", return_value=info):
        upgrade, reason = should_upgrade_model()
    assert upgrade is True
    assert "window ending" in reason


def test_should_upgrade_no_surplus():
    """Window ending soon but quota mostly used -> no upgrade."""
    now = datetime.now()
    window_start = now - timedelta(hours=4)
    info = {
        "window_start": window_start,
        "window_end": window_start + timedelta(hours=5),
        "remaining_pct": 10.0,
        "model": constants.DEFAULT_MODEL,
        "model_limit": 225,
        "estimated_limit": 225,
        "used": 202,
        "remaining": 23,
        "safety_reserved": 33,
        "available_for_autonomous": 0,
    }
    with patch("wise_magpie.quota.estimator.estimate_remaining", return_value=info):
        upgrade, _ = should_upgrade_model()
    assert upgrade is False


# --- select_model ---

def test_select_model_auto_disabled():
    """When auto_select_model=false, return configured default."""
    cfg = {"claude": {"model": "opus", "auto_select_model": False}}
    task = Task(title="Whatever")
    with patch("wise_magpie.tasks.model_selector.config.load_config", return_value=cfg):
        result = select_model(task)
    assert result == "claude-opus-4-6"


def test_select_model_explicit_model_on_task():
    """Task with explicit model -> use that model."""
    task = Task(title="Whatever", model="haiku")
    result = select_model(task)
    assert result == "claude-haiku-4-5-20251001"


def test_select_model_security_task_gets_opus():
    """Security-related task -> complex -> opus."""
    task = Task(title="Fix security vulnerability", description="XSS attack vector")
    with patch("wise_magpie.tasks.model_selector.should_upgrade_model", return_value=(False, "")), \
         patch("wise_magpie.tasks.model_selector._has_model_quota", return_value=True):
        result = select_model(task)
    assert result == "claude-opus-4-6"


def test_select_model_docs_task_gets_haiku():
    """Documentation task -> simple -> haiku."""
    task = Task(title="Update docs", description="Fix typo in readme")
    with patch("wise_magpie.tasks.model_selector.should_upgrade_model", return_value=(False, "")), \
         patch("wise_magpie.tasks.model_selector._has_model_quota", return_value=True):
        result = select_model(task)
    assert result == "claude-haiku-4-5-20251001"


def test_select_model_downgrade_on_no_quota():
    """When target model has no quota, downgrade."""
    task = Task(title="Fix security bug", description="Critical vulnerability")

    def mock_has_quota(model: str) -> bool:
        return model != "claude-opus-4-6"

    with patch("wise_magpie.tasks.model_selector.should_upgrade_model", return_value=(False, "")), \
         patch("wise_magpie.tasks.model_selector._has_model_quota", side_effect=mock_has_quota):
        result = select_model(task)
    assert result == "claude-sonnet-4-5-20250929"


def test_select_model_upgrade_on_surplus():
    """Surplus quota -> upgrade model one level."""
    task = Task(
        title="Implement feature",
        description=(
            "Add user profile editing with form validation and state management "
            "for the user settings. Include avatar upload and email change functionality."
        ),
    )

    with patch("wise_magpie.tasks.model_selector.should_upgrade_model", return_value=(True, "surplus")), \
         patch("wise_magpie.tasks.model_selector._has_model_quota", return_value=True):
        result = select_model(task)
    # Medium task -> sonnet, upgraded -> opus
    assert result == "claude-opus-4-6"


# --- DB integration ---

def test_get_model_usage_count():
    """get_model_usage_count returns correct count for a specific model."""
    from wise_magpie.quota.tracker import record_usage

    record_usage(model="claude-opus-4-6", input_tokens=100, output_tokens=50, autonomous=True)
    record_usage(model="claude-opus-4-6", input_tokens=200, output_tokens=100, autonomous=True)
    record_usage(model="claude-sonnet-4-5-20250929", input_tokens=100, output_tokens=50, autonomous=True)

    since = datetime.now() - timedelta(hours=1)
    opus_count = db.get_model_usage_count("claude-opus-4-6", since)
    sonnet_count = db.get_model_usage_count("claude-sonnet-4-5-20250929", since)

    assert opus_count == 2
    assert sonnet_count == 1


def test_quota_correction_session():
    """Session percentage correction should be recorded and affect remaining estimate."""
    from wise_magpie.quota.corrections import apply_correction
    from wise_magpie.quota.estimator import estimate_remaining
    from wise_magpie import constants

    apply_correction(session=50)  # 50% used in current session

    window = db.get_current_quota_window()
    assert window is not None

    sonnet_id = constants.MODEL_ALIASES["sonnet"]
    correction = db.get_latest_quota_correction(window.id, sonnet_id)  # type: ignore[arg-type]
    assert correction is not None
    assert correction["scope"] == "session"
    assert correction["remaining"] == 50  # stored as pct_used

    est = estimate_remaining(model=sonnet_id)
    sonnet_limit = est["estimated_limit"]
    # Remaining should be roughly 50% of limit
    assert est["remaining"] <= sonnet_limit // 2 + 1


def test_task_model_field_persists():
    """Task.model field should be saved and loaded from DB."""
    task = Task(title="Test", model="claude-opus-4-6")
    task_id = db.insert_task(task)

    fetched = db.get_task(task_id)
    assert fetched is not None
    assert fetched.model == "claude-opus-4-6"


def test_task_model_field_update():
    """Task.model should be updatable."""
    task = Task(title="Test")
    task.id = db.insert_task(task)
    assert task.model == ""

    task.model = "claude-haiku-4-5-20251001"
    db.update_task(task)

    fetched = db.get_task(task.id)
    assert fetched.model == "claude-haiku-4-5-20251001"
