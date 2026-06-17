"""Slash command support for /icr."""

from __future__ import annotations

import shlex
from typing import Any

from .json_utils import dumps
from .tools import make_handlers


def make_icr_command(ctx: Any):
    handlers = make_handlers(ctx)

    def handle(raw_args: str) -> str:
        args = parse_icr_args(raw_args)
        action = args.pop("action", "run")
        if action == "run":
            return handlers["icr_run"](args)
        if action == "status":
            return handlers["icr_status"](args)
        if action == "export":
            return handlers["icr_export"](args)
        if action == "list":
            return handlers["icr_list_runs"](args)
        return dumps({"success": False, "error": f"Unknown /icr action: {action}"})

    return handle


def parse_icr_args(raw: str) -> dict[str, Any]:
    tokens = shlex.split(raw or "")
    if not tokens:
        return {"action": "list"}
    action = tokens[0].lower()
    args: dict[str, Any] = {"action": action}
    rest = tokens[1:]
    if action == "run":
        if not rest:
            raise ValueError("/icr run requires a mode and challenge text")
        args["mode"] = rest[0]
        args["challenge"] = " ".join(rest[1:])
    elif action == "status":
        if not rest:
            raise ValueError("/icr status requires run_id")
        args["run_id"] = rest[0]
    elif action == "export":
        if not rest:
            raise ValueError("/icr export requires run_id")
        args["run_id"] = rest[0]
        if len(rest) > 1:
            args["format"] = rest[1]
    elif action == "list":
        if rest:
            args["limit"] = int(rest[0])
    else:
        args["challenge"] = " ".join(rest)
    return args

