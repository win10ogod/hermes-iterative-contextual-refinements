"""Process-local background execution for ICR runs."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any

from .config import build_config
from .constants import ICR_MODES
from .json_utils import utc_now_iso
from .persistence import RunStore
from .progress import RunProgress
from .run_record import mark_error, new_run
from .runner import ICRRunner


@dataclass
class BackgroundEntry:
    run_id: str
    thread: threading.Thread
    started_at: str


class BackgroundRunManager:
    """Start ICR runs in daemon threads and expose process-local liveness."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, BackgroundEntry] = {}

    def start(self, *, ctx_llm: Any, store: RunStore, args: dict[str, Any]) -> dict[str, Any]:
        mode = str(args.get("mode") or "").strip()
        if mode not in ICR_MODES:
            raise ValueError(f"mode must be one of: {', '.join(ICR_MODES)}")
        cfg = build_config(args.get("config") or {}, mode=mode)
        run_id = str(args.get("run_id") or f"icr-{uuid.uuid4().hex[:12]}")
        if store.path_for(run_id).exists():
            raise FileExistsError(f"ICR run already exists: {run_id}")

        request = {
            "mode": mode,
            "challenge": args.get("challenge") or "",
            "content": args.get("content") or "",
            "instruction": args.get("instruction") or "",
        }
        thread_name = f"icr-start-{run_id}"
        record = new_run(mode, request, cfg.as_dict(), run_id=run_id)
        record["status"] = "queued"
        record["background"] = {
            "status": "queued",
            "started_by": "icr_start",
            "queued_at": utc_now_iso(),
            "process_local": True,
            "thread_name": thread_name,
        }
        progress = RunProgress(record, store, cfg)
        progress.touch("background", "queued", "icr_start accepted the background run", mode=mode)

        worker_args = dict(args)
        worker_args["run_id"] = run_id
        worker_args["_initial_record"] = record
        worker_args["_background"] = {
            "status": "processing",
            "started_by": "icr_start",
            "queued_at": record["background"]["queued_at"],
            "started_at": utc_now_iso(),
            "process_local": True,
            "thread_name": thread_name,
        }
        thread = threading.Thread(
            target=self._worker,
            name=thread_name,
            args=(ctx_llm, store, worker_args),
            daemon=True,
        )
        with self._lock:
            self._entries[run_id] = BackgroundEntry(run_id=run_id, thread=thread, started_at=worker_args["_background"]["started_at"])
        thread.start()
        return record

    def state_for(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            entry = self._entries.get(run_id)
        if entry is None:
            return {"process_local_thread_known": False}
        return {
            "process_local_thread_known": True,
            "thread_alive": entry.thread.is_alive(),
            "thread_name": entry.thread.name,
            "thread_started_at": entry.started_at,
        }

    def _worker(self, ctx_llm: Any, store: RunStore, args: dict[str, Any]) -> None:
        run_id = str(args["run_id"])
        try:
            ICRRunner(ctx_llm, store).run(args)
            self._mark_background_status(store, run_id, "completed")
        except BaseException as exc:
            try:
                record = store.load(run_id)
            except Exception:
                mode = str(args.get("mode") or "unknown")
                record = new_run(mode, {}, {}, run_id=run_id)
            if record.get("status") != "error":
                mark_error(record, exc)
            background = record.setdefault("background", {})
            background.update({"status": "error", "completed_at": utc_now_iso(), "error_type": type(exc).__name__, "error": str(exc)})
            store.save(record)
        finally:
            with self._lock:
                self._entries.pop(run_id, None)

    def _mark_background_status(self, store: RunStore, run_id: str, status: str) -> None:
        record = store.load(run_id)
        background = record.setdefault("background", {})
        background.update({"status": status, "completed_at": utc_now_iso()})
        store.save(record)


DEFAULT_BACKGROUND_MANAGER = BackgroundRunManager()
