"""Tests for BLE GATT command handler."""

from __future__ import annotations

import json

from wise_magpie.ble.handler import dispatch, get_status_snapshot


def test_dispatch_status():
    result = json.loads(dispatch(b'{"cmd": "status"}'))
    assert result["ok"] is True
    assert "daemon" in result["data"]
    assert "pending_tasks" in result["data"]
    assert "running_tasks" in result["data"]


def test_dispatch_tasks_empty():
    result = json.loads(dispatch(b'{"cmd": "tasks"}'))
    assert result["ok"] is True
    assert result["data"] == []


def test_dispatch_add_task():
    result = json.loads(dispatch(b'{"cmd": "add", "title": "BLE test task"}'))
    assert result["ok"] is True
    assert result["data"]["title"] == "BLE test task"
    assert "task_id" in result["data"]


def test_dispatch_add_then_list():
    dispatch(b'{"cmd": "add", "title": "Listed task"}')
    result = json.loads(dispatch(b'{"cmd": "tasks"}'))
    assert result["ok"] is True
    titles = [t["title"] for t in result["data"]]
    assert "Listed task" in titles


def test_dispatch_add_missing_title():
    result = json.loads(dispatch(b'{"cmd": "add"}'))
    assert result["ok"] is False
    assert "title" in result["error"].lower()


def test_dispatch_quota():
    result = json.loads(dispatch(b'{"cmd": "quota"}'))
    assert result["ok"] is True
    for model in ("opus", "sonnet", "haiku"):
        assert model in result["data"]
        assert "remaining" in result["data"][model]


def test_dispatch_unknown_command():
    result = json.loads(dispatch(b'{"cmd": "nope"}'))
    assert result["ok"] is False
    assert "Unknown command" in result["error"]


def test_dispatch_invalid_json():
    result = json.loads(dispatch(b"not json"))
    assert result["ok"] is False
    assert "Invalid JSON" in result["error"]


def test_dispatch_missing_cmd_field():
    result = json.loads(dispatch(b'{"foo": "bar"}'))
    assert result["ok"] is False
    assert "cmd" in result["error"]


def test_get_status_snapshot():
    data = json.loads(get_status_snapshot())
    assert "daemon" in data


def test_dispatch_add_with_priority():
    payload = json.dumps({"cmd": "add", "title": "High pri", "priority": 90}).encode()
    result = json.loads(dispatch(payload))
    assert result["ok"] is True
    assert result["data"]["title"] == "High pri"
