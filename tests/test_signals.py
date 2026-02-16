"""Tests for daemon signal handling."""

from __future__ import annotations

import threading

from wise_magpie.daemon.signals import SignalHandler


def test_initial_state():
    handler = SignalHandler()
    assert handler.should_stop is False


def test_handle_sets_shutdown():
    handler = SignalHandler()
    handler._handle(15, None)  # Simulate SIGTERM
    assert handler.should_stop is True


def test_wait_returns_immediately_after_signal():
    handler = SignalHandler()
    handler._handle(2, None)  # Simulate SIGINT
    assert handler.wait(timeout=5.0) is True


def test_wait_timeout():
    handler = SignalHandler()
    result = handler.wait(timeout=0.05)
    assert result is False
    assert handler.should_stop is False


def test_cross_thread_release():
    handler = SignalHandler()

    def trigger():
        handler._handle(15, None)

    t = threading.Thread(target=trigger)
    t.start()
    result = handler.wait(timeout=5.0)
    t.join()
    assert result is True
    assert handler.should_stop is True
