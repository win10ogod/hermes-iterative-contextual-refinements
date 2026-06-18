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


def heartbeat_stale_seconds(default: float | None = None) -> float | None:
    raw = os.getenv("HERMES_ICR_HEARTBEAT_STALE_SECONDS", "")
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
        stale_after_seconds: float | None = None,
    ) -> None:
        self.label = label
        self.callback = callback
        self.interval_seconds = interval_seconds or heartbeat_interval_seconds()
        self.stale_after_seconds = stale_after_seconds or heartbeat_stale_seconds()
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._start = 0.0
        self._last_progress = 0.0
        self._last_progress_label = "started"
        self._stale_reported = False

    def __enter__(self) -> "ActivityHeartbeat":
        self.callback = self.callback or current_activity_callback()
        if self.callback is None:
            return self
        self._start = time.monotonic()
        self._last_progress = self._start
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

    def mark_progress(self, label: str) -> None:
        with self._lock:
            self._last_progress = time.monotonic()
            self._last_progress_label = label
        self._touch(f"progress: {label}")

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            stale_status = self._stale_status()
            if stale_status is not None:
                self._touch(stale_status)
                return
            self._touch(self._running_status())

    def _running_status(self) -> str:
        with self._lock:
            age = int(time.monotonic() - self._last_progress) if self._last_progress else 0
            label = self._last_progress_label
        return f"running; last progress {age}s ago: {label}"

    def _stale_status(self) -> str | None:
        stale_after = self.stale_after_seconds
        if stale_after is None or stale_after <= 0:
            return None
        with self._lock:
            last_progress = self._last_progress
            label = self._last_progress_label
            if self._stale_reported or not last_progress:
                return None
            age = time.monotonic() - last_progress
            if age < stale_after:
                return None
            self._stale_reported = True
        return f"stale; heartbeat stopped after {int(age)}s without progress: {label}"

    def _touch(self, status: str) -> None:
        callback = self.callback
        if callback is None:
            return
        try:
            elapsed = int(time.monotonic() - self._start) if self._start else 0
            callback(f"{self.label}: {status} ({elapsed}s elapsed)")
        except Exception:
            pass
