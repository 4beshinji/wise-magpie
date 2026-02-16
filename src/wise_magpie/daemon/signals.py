"""Signal handling for the daemon."""

from __future__ import annotations

import signal
import threading


class SignalHandler:
    """Manages graceful shutdown via signals."""

    def __init__(self) -> None:
        self._shutdown = threading.Event()

    def install(self) -> None:
        """Install signal handlers for SIGTERM and SIGINT."""
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT, self._handle)

    def _handle(self, signum: int, frame: object) -> None:
        self._shutdown.set()

    @property
    def should_stop(self) -> bool:
        return self._shutdown.is_set()

    def wait(self, timeout: float) -> bool:
        """Wait for shutdown signal. Returns True if signal received."""
        return self._shutdown.wait(timeout)
