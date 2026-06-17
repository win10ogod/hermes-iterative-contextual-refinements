"""Run record construction and mutation helpers."""

from __future__ import annotations

import uuid
from typing import Any

from .json_utils import utc_now_iso


def new_run(mode: str, request: dict[str, Any], config: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": "icr.hermes.run.v1",
        "run_id": run_id or f"icr-{uuid.uuid4().hex[:12]}",
        "mode": mode,
        "status": "processing",
        "created_at": now,
        "updated_at": now,
        "request": request,
        "config": config,
        "artifacts": {},
        "llm_calls": [],
        "events": [],
        "errors": [],
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        },
    }


def event(record: dict[str, Any], kind: str, message: str, **data: Any) -> None:
    record.setdefault("events", []).append(
        {
            "time": utc_now_iso(),
            "kind": kind,
            "message": message,
            "data": data,
        }
    )
    record["updated_at"] = utc_now_iso()


def mark_error(record: dict[str, Any], exc: BaseException) -> None:
    record["status"] = "error"
    record.setdefault("errors", []).append(
        {
            "time": utc_now_iso(),
            "type": type(exc).__name__,
            "message": str(exc),
        }
    )
    record["updated_at"] = utc_now_iso()


def mark_completed(record: dict[str, Any]) -> None:
    record["status"] = "completed"
    record["updated_at"] = utc_now_iso()

