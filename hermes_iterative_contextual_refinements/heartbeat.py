"""Hermes gateway activity heartbeats for long ICR tool calls."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from types import TracebackType


ActivityCallback = Callable[[str], None]


def current_activity_callback() -> ActivityCallback | None:
    """Return Hermes' current tool activity callback when running in Hermes."""
    try:
        from tools.environments.base import _get_activity_callback  # type: ignore
    except Exception:
        return None
    try:
        callback = _get_activity_callback()
    except Exception:
        return None
    return callback if callable(callback) else None


def heartbeat_interval_seconds(default: float = 10.0) -> float:
    raw = os.getenv("HERMES_ICR_ACTIVITY_HEARTBEAT_SECONDS", "")
    if not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class ActivityHeartbeat:
    """Periodically touch Hermes activity while a synchronous tool keeps working."""

    def __init__(
        self,
        label: str,
        *,
        callback: ActivityCallback | None = None,
        interval_seconds: float | None = None,
    ) -> None:
        self.label = label
        self.callback = callback
        self.interval_seconds = interval_seconds or heartbeat_interval_seconds()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start = 0.0

    def __enter__(self) -> "ActivityHeartbeat":
        self.callback = self.callback or current_activity_callback()
        if self.callback is None:
            return self
        self._start = time.monotonic()
        self._touch("started")
        self._thread = threading.Thread(
            target=self._run,
            name="icr-activity-heartbeat",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._touch("completed" if exc_type is None else "failed")

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._touch("running")

    def _touch(self, status: str) -> None:
        callback = self.callback
        if callback is None:
            return
        try:
            elapsed = int(time.monotonic() - self._start) if self._start else 0
            callback(f"{self.label}: {status} ({elapsed}s elapsed)")
        except Exception:
            pass
