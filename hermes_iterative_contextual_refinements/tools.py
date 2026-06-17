"""Hermes tool handlers for ICR."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .heartbeat import ActivityHeartbeat
from .json_utils import dumps
from .persistence import RunStore
from .runner import ICRRunner


def make_handlers(ctx: Any, store: RunStore | None = None) -> dict[str, Any]:
    run_store = store or RunStore()

    def icr_run(args: dict[str, Any], **_: Any) -> str:
        mode = str(args.get("mode") or "unknown")
        with ActivityHeartbeat(f"ICR run {mode}"):
            record = ICRRunner(ctx.llm, run_store).run(args)
        return dumps(
            {
                "success": True,
                "run_id": record["run_id"],
                "mode": record["mode"],
                "status": record["status"],
                "path": str(run_store.path_for(record["run_id"])),
                "final": record.get("artifacts", {}).get("final"),
                "usage": record.get("usage", {}),
                "semantic_adjustments": record.get("config", {}).get("semantic_adjustments", []),
            }
        )

    def icr_status(args: dict[str, Any], **_: Any) -> str:
        run = run_store.load(str(args["run_id"]))
        return dumps(
            {
                "success": True,
                "run_id": run.get("run_id"),
                "mode": run.get("mode"),
                "status": run.get("status"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "errors": run.get("errors", []),
                "usage": run.get("usage", {}),
                "artifact_keys": sorted((run.get("artifacts") or {}).keys()),
                "llm_call_count": len(run.get("llm_calls", [])),
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
        "icr_status": icr_status,
        "icr_export": icr_export,
        "icr_list_runs": icr_list_runs,
    }
