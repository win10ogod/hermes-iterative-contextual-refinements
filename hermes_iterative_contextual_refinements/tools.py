"""Hermes tool handlers for ICR."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .background import DEFAULT_BACKGROUND_MANAGER, BackgroundRunManager
from .heartbeat import ActivityHeartbeat
from .json_utils import dumps, utc_now_iso
from .persistence import RunStore
from .runner import ICRRunner


def make_handlers(ctx: Any, store: RunStore | None = None, background_manager: BackgroundRunManager | None = None) -> dict[str, Any]:
    run_store = store or RunStore()
    bg_manager = background_manager or DEFAULT_BACKGROUND_MANAGER

    def icr_run(args: dict[str, Any], **_: Any) -> str:
        mode = str(args.get("mode") or "unknown")
        stale_after = _positive_config_value(args, "heartbeat_stale_seconds")
        with ActivityHeartbeat(f"ICR run {mode}", stale_after_seconds=stale_after) as heartbeat:
            record = ICRRunner(ctx.llm, run_store).run(args, activity=heartbeat)
            heartbeat.mark_progress("handler:serializing_result")
            _mark_handler_progress(record, "serializing_result", mode=mode)
        return dumps(
            {
                "success": True,
                "run_id": record["run_id"],
                "mode": record["mode"],
                "status": record["status"],
                "path": str(run_store.path_for(record["run_id"])),
                "final_available": _has_final(record),
                "artifact_keys": sorted((record.get("artifacts") or {}).keys()),
                "usage": record.get("usage", {}),
                "progress": _compact_progress(record.get("progress", {})),
                "checkpoint_count": len(record.get("checkpoints", [])),
                "last_checkpoint": _last_checkpoint(record),
                "resume_metadata": record.get("resume_metadata", {}),
                "active_llm_calls": _active_llm_calls(record),
                "result_policy": "Full final output is omitted from icr_run to keep the tool response small. Use icr_export for JSON or Markdown results.",
                "export_hint": {"tool": "icr_export", "args": {"run_id": record["run_id"], "format": "markdown"}},
                "semantic_adjustments": record.get("config", {}).get("semantic_adjustments", []),
            }
        )

    def icr_start(args: dict[str, Any], **_: Any) -> str:
        record = bg_manager.start(ctx_llm=ctx.llm, store=run_store, args=args)
        run_id = record["run_id"]
        return dumps(
            {
                "success": True,
                "run_id": run_id,
                "mode": record.get("mode"),
                "status": record.get("status"),
                "path": str(run_store.path_for(run_id)),
                "background": {**(record.get("background") or {}), **bg_manager.state_for(run_id)},
                "progress": _compact_progress(record.get("progress", {})),
                "checkpoint_count": len(record.get("checkpoints", [])),
                "last_checkpoint": _last_checkpoint(record),
                "result_policy": "icr_start returns immediately and the run continues in this Hermes process. Poll icr_status and export completed results with icr_export.",
                "status_hint": {"tool": "icr_status", "args": {"run_id": run_id}},
                "export_hint": {"tool": "icr_export", "args": {"run_id": run_id, "format": "markdown"}},
            }
        )

    def icr_status(args: dict[str, Any], **_: Any) -> str:
        run = run_store.load(str(args["run_id"]))
        background = run.get("background") or {}
        if isinstance(background, dict):
            background = {**background, **bg_manager.state_for(str(args["run_id"]))}
        else:
            background = bg_manager.state_for(str(args["run_id"]))
        return dumps(
            {
                "success": True,
                "run_id": run.get("run_id"),
                "mode": run.get("mode"),
                "status": _effective_status(run),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "errors": run.get("errors", []),
                "usage": run.get("usage", {}),
                "progress": _compact_progress(run.get("progress", {})),
                "checkpoint_count": len(run.get("checkpoints", [])),
                "last_checkpoint": _last_checkpoint(run),
                "resume_metadata": run.get("resume_metadata", {}),
                "background": background,
                "active_llm_calls": _active_llm_calls(run),
                "artifact_keys": sorted((run.get("artifacts") or {}).keys()),
                "llm_call_count": len(run.get("llm_calls", [])),
                "final_available": _has_final(run),
                "export_hint": {"tool": "icr_export", "args": {"run_id": run.get("run_id"), "format": "markdown"}},
            }
        )

    def icr_export(args: dict[str, Any], **_: Any) -> str:
        run_id = str(args["run_id"])
        fmt = str(args.get("format") or "json").lower()
        if fmt in {"md", "markdown"}:
            content = run_store.export_markdown(run_id)
            fmt = "markdown"
        elif fmt == "json":
            content = run_store.export_json(run_id)
        else:
            raise ValueError("format must be json or markdown")
        output_path = args.get("output_path")
        written = None
        if output_path:
            path = Path(str(output_path)).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written = str(path)
        return dumps({"success": True, "run_id": run_id, "format": fmt, "content": content, "written": written})

    def icr_list_runs(args: dict[str, Any], **_: Any) -> str:
        limit = int(args.get("limit") or 20)
        limit = max(1, min(limit, 200))
        rows = run_store.list_runs(limit=limit, status=args.get("status"), mode=args.get("mode"))
        return dumps({"success": True, "runs": rows})

    return {
        "icr_run": icr_run,
        "icr_start": icr_start,
        "icr_status": icr_status,
        "icr_export": icr_export,
        "icr_list_runs": icr_list_runs,
    }


def _positive_config_value(args: dict[str, Any], key: str) -> float | None:
    config = args.get("config") or {}
    if not isinstance(config, dict):
        return None
    raw = config.get(key)
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _mark_handler_progress(record: dict[str, Any], status: str, **details: Any) -> None:
    now = utc_now_iso()
    progress = record.setdefault("progress", {})
    event = {
        "timestamp": now,
        "stage": "handler",
        "status": status,
        "message": "icr_run handler is preparing the tool response",
        "details": details,
    }
    progress["current"] = event
    progress["last_progress_at"] = now
    progress.setdefault("events", []).append(event)
    record["updated_at"] = now


def _compact_progress(progress: dict[str, Any], *, recent_event_limit: int = 5) -> dict[str, Any]:
    events = progress.get("events") if isinstance(progress, dict) else []
    if not isinstance(events, list):
        events = []
    return {
        "current": progress.get("current") if isinstance(progress, dict) else None,
        "started_at": progress.get("started_at") if isinstance(progress, dict) else None,
        "last_progress_at": progress.get("last_progress_at") if isinstance(progress, dict) else None,
        "elapsed_seconds": progress.get("elapsed_seconds") if isinstance(progress, dict) else None,
        "deadline_seconds": progress.get("deadline_seconds") if isinstance(progress, dict) else None,
        "heartbeat_stale_seconds": progress.get("heartbeat_stale_seconds") if isinstance(progress, dict) else None,
        "checkpoint_count": progress.get("checkpoint_count") if isinstance(progress, dict) else None,
        "last_checkpoint": progress.get("last_checkpoint") if isinstance(progress, dict) else None,
        "event_count": len(events),
        "recent_events": events[-recent_event_limit:],
    }


def _has_final(run: dict[str, Any]) -> bool:
    artifacts = run.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return False
    return any(key in artifacts and artifacts.get(key) not in (None, "", {}, []) for key in ("final", "selected_solution", "final_content"))


def _effective_status(run: dict[str, Any]) -> str | None:
    status = run.get("status")
    if status != "completed":
        return status
    progress = run.get("progress") if isinstance(run.get("progress"), dict) else {}
    current = progress.get("current") if isinstance(progress, dict) else {}
    if not isinstance(current, dict):
        return "processing"
    if current.get("stage") == "runner" and current.get("status") == "completed":
        return "completed"
    return "processing"


def _active_llm_calls(run: dict[str, Any]) -> list[dict[str, Any]]:
    active = []
    for call in run.get("llm_calls", []):
        if not isinstance(call, dict) or call.get("status") != "processing":
            continue
        attempts = call.get("attempts") or []
        last_attempt = attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}
        active.append(
            {
                "id": call.get("id"),
                "role": call.get("role"),
                "purpose": call.get("purpose"),
                "kind": call.get("kind"),
                "status": call.get("status"),
                "created_at": call.get("created_at"),
                "attempt_count": len(attempts),
                "last_attempt": last_attempt,
            }
        )
    return active


def _last_checkpoint(run: dict[str, Any]) -> dict[str, Any] | None:
    checkpoints = run.get("checkpoints")
    if isinstance(checkpoints, list) and checkpoints and isinstance(checkpoints[-1], dict):
        return checkpoints[-1]
    return None
