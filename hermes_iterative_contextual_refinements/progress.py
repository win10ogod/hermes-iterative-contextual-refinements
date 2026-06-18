"""Durable progress tracking for ICR runs."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any

from .config import ICRConfig
from .heartbeat import ActivityHeartbeat
from .json_utils import utc_now_iso
from .persistence import RunStore


class RunProgress:
    """Persist observable run progress and enforce optional explicit deadlines."""

    def __init__(
        self,
        record: dict[str, Any],
        store: RunStore,
        config: ICRConfig,
        *,
        activity: ActivityHeartbeat | None = None,
    ) -> None:
        self.record = record
        self.store = store
        self.config = config
        self.activity = activity
        self._lock = threading.RLock()
        self._start = time.monotonic()
        progress = self.record.setdefault("progress", {})
        progress.setdefault("started_at", utc_now_iso())
        progress.setdefault("events", [])
        progress.setdefault("deadline_seconds", config.run_deadline_seconds)
        progress.setdefault("heartbeat_stale_seconds", config.heartbeat_stale_seconds)

    def touch(self, stage: str, status: str, message: str = "", **details: Any) -> None:
        now = utc_now_iso()
        elapsed = self.elapsed_seconds()
        event = {
            "timestamp": now,
            "elapsed_seconds": elapsed,
            "stage": stage,
            "status": status,
            "message": message,
            "details": details,
        }
        with self._lock:
            progress = self.record.setdefault("progress", {})
            progress["current"] = event
            progress["last_progress_at"] = now
            progress["elapsed_seconds"] = elapsed
            progress["deadline_seconds"] = self.config.run_deadline_seconds
            progress["heartbeat_stale_seconds"] = self.config.heartbeat_stale_seconds
            progress.setdefault("events", []).append(event)
            self.record["updated_at"] = now
            self._save_observable_snapshot_locked()
        if self.activity is not None:
            label = f"{stage}:{status}"
            if message:
                label = f"{label} {message}"
            self.activity.mark_progress(label)

    def save_record(self) -> None:
        with self._lock:
            self.record["updated_at"] = utc_now_iso()
            progress = self.record.setdefault("progress", {})
            progress["elapsed_seconds"] = self.elapsed_seconds()
            self._save_observable_snapshot_locked()

    def upsert_llm_call(self, call: dict[str, Any]) -> None:
        with self._lock:
            calls = self.record.setdefault("llm_calls", [])
            for index, existing in enumerate(calls):
                if existing.get("id") == call.get("id"):
                    calls[index] = call
                    break
            else:
                calls.append(call)
            self.record["updated_at"] = utc_now_iso()
            self._save_observable_snapshot_locked()

    def check_deadline(self, stage: str) -> None:
        deadline = self.config.run_deadline_seconds
        if deadline is None or deadline <= 0:
            return
        elapsed = self.elapsed_seconds()
        if elapsed <= deadline:
            return
        self.touch(
            stage,
            "deadline_exceeded",
            f"ICR run exceeded run_deadline_seconds={deadline:g}",
            deadline_seconds=deadline,
            elapsed_seconds=elapsed,
        )
        raise TimeoutError(f"ICR run exceeded run_deadline_seconds={deadline:g}s at {stage}")

    def elapsed_seconds(self) -> float:
        return round(time.monotonic() - self._start, 3)

    def _save_observable_snapshot_locked(self) -> None:
        snapshot: dict[str, Any] = {}
        for key in (
            "run_id",
            "mode",
            "status",
            "created_at",
            "updated_at",
            "request",
            "config",
            "errors",
            "usage",
            "llm_calls",
            "progress",
        ):
            if key in self.record:
                snapshot[key] = _safe_deepcopy(self.record[key])
        if self.record.get("status") != "processing":
            snapshot["artifacts"] = _safe_deepcopy(self.record.get("artifacts", {}))
        else:
            snapshot["artifacts"] = {}
        self.store.save(snapshot)


def _safe_deepcopy(value: Any) -> Any:
    for _ in range(3):
        try:
            return deepcopy(value)
        except RuntimeError:
            time.sleep(0.001)
    return None
