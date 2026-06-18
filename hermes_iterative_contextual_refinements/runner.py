"""Unified run dispatcher for all ICR modes."""

from __future__ import annotations

from typing import Any

from .adaptive import AdaptiveDeepthinkEngine
from .agentic import AgenticRefinementEngine
from .config import build_config
from .constants import ICR_MODES
from .contextual import ContextualRefinementEngine
from .dca import DCAEngine
from .deepthink import DeepthinkEngine
from .json_utils import utc_now_iso
from .llm import ICRLlm
from .persistence import RunStore
from .progress import RunProgress
from .run_record import mark_completed, mark_error, new_run
from .state_machine import attach_state_machine


class ICRRunner:
    def __init__(self, ctx_llm: Any, store: RunStore | None = None):
        self.ctx_llm = ctx_llm
        self.store = store or RunStore()

    def run(self, args: dict[str, Any], *, activity: Any = None) -> dict[str, Any]:
        mode = str(args.get("mode") or "").strip()
        if mode not in ICR_MODES:
            raise ValueError(f"mode must be one of: {', '.join(ICR_MODES)}")
        cfg = build_config(args.get("config") or {}, mode=mode)
        request = {
            "mode": mode,
            "challenge": args.get("challenge") or "",
            "content": args.get("content") or "",
            "instruction": args.get("instruction") or "",
        }
        initial_record = args.get("_initial_record")
        if isinstance(initial_record, dict):
            record = initial_record
            record["status"] = "processing"
            record["updated_at"] = utc_now_iso()
            record["request"] = request
            record["config"] = cfg.as_dict()
        else:
            record = new_run(mode, request, cfg.as_dict(), run_id=args.get("run_id"))
        background = args.get("_background")
        if isinstance(background, dict):
            record["background"] = dict(background)
        self.store.save(record)
        progress = RunProgress(record, self.store, cfg, activity=activity)
        if activity is not None and cfg.heartbeat_stale_seconds is not None:
            activity.stale_after_seconds = cfg.heartbeat_stale_seconds
        progress.touch("runner", "started", mode=mode)
        llm = ICRLlm(self.ctx_llm, record, cfg, progress=progress)
        try:
            progress.check_deadline("runner.dispatch")
            if mode == "deepthink":
                challenge = _require_text(args, "challenge")
                DeepthinkEngine(llm, record, cfg).run_single_pass(challenge)
            elif mode == "evolving_deepthink":
                challenge = _require_text(args, "challenge")
                DeepthinkEngine(llm, record, cfg).run_evolving_dfs(challenge)
            elif mode == "adaptive_deepthink":
                challenge = _require_text(args, "challenge")
                AdaptiveDeepthinkEngine(llm, record, cfg).run(challenge)
            elif mode == "contextual_refinement":
                challenge = _require_text(args, "challenge")
                ContextualRefinementEngine(llm, record, cfg).run(challenge)
            elif mode == "agentic_refinement":
                content = _require_text(args, "content")
                AgenticRefinementEngine(llm, record, cfg).run(content, str(args.get("instruction") or ""))
            elif mode == "dca":
                challenge = _require_text(args, "challenge")
                DCAEngine(llm, record, cfg).run(challenge)
            progress.touch("runner", "mode_completed", mode=mode)
            mark_completed(record)
            progress.touch("state_machine", "attaching", mode=mode)
            attach_state_machine(record)
            progress.touch("state_machine", "attached", mode=mode)
            _mark_background(record, "completed")
            progress.touch("runner", "completed", mode=mode)
        except BaseException as exc:
            mark_error(record, exc)
            _mark_background(record, "error", error_type=type(exc).__name__, error=str(exc))
            progress.touch("state_machine", "attaching_after_error", mode=mode, error_type=type(exc).__name__)
            attach_state_machine(record)
            progress.touch("runner", "error", str(exc), error_type=type(exc).__name__, mode=mode)
            raise
        finally:
            llm.close()
        self.store.save(record)
        return record


def _require_text(args: dict[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required for this ICR mode")
    return value


def _mark_background(record: dict[str, Any], status: str, **details: Any) -> None:
    background = record.get("background")
    if not isinstance(background, dict):
        return
    background.update({"status": status, "completed_at": utc_now_iso(), **details})
