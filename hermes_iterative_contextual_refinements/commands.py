"""Slash command support for /icr."""

from __future__ import annotations

import json
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
        if action == "start":
            return handlers["icr_start"](args)
        if action == "status":
            return handlers["icr_status"](args)
        if action == "export":
            return handlers["icr_export"](args)
        if action == "list":
            return handlers["icr_list_runs"](args)
        if action == "doctor":
            from .doctor import diagnose

            return dumps(diagnose(platform=args.get("platform", "cli")))
        return dumps({"success": False, "error": f"Unknown /icr action: {action}"})

    return handle


def parse_icr_args(raw: str) -> dict[str, Any]:
    tokens = shlex.split(raw or "")
    if not tokens:
        return {"action": "list"}
    action = tokens[0].lower()
    args: dict[str, Any] = {"action": action}
    rest = tokens[1:]
    if action in {"run", "start"}:
        args.update(_parse_run_args(rest))
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
        if len(rest) > 2:
            args["output_path"] = rest[2]
    elif action == "list":
        if rest:
            args["limit"] = int(rest[0])
        if len(rest) > 1:
            args["status"] = rest[1]
        if len(rest) > 2:
            args["mode"] = rest[2]
    elif action == "doctor":
        args["platform"] = "cli"
        index = 0
        while index < len(rest):
            token = rest[index]
            if token == "--platform":
                args["platform"], index = _next_value(rest, index, token)
            elif index == 0:
                args["platform"] = token
            else:
                raise ValueError(f"Unknown /icr doctor option: {token}")
            index += 1
    else:
        args["challenge"] = " ".join(rest)
    return args


def _parse_run_args(tokens: list[str]) -> dict[str, Any]:
    if not tokens:
        raise ValueError("/icr run/start requires a mode and challenge text")
    mode = tokens[0]
    args: dict[str, Any] = {"mode": mode}
    positionals: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            positionals.extend(tokens[index + 1 :])
            break
        if token in {"--config-json", "--config"}:
            value, index = _next_value(tokens, index, token)
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError(f"{token} must be a JSON object")
            args["config"] = parsed
        elif token == "--run-id":
            args["run_id"], index = _next_value(tokens, index, token)
        elif token == "--content":
            args["content"], index = _next_value(tokens, index, token)
        elif token == "--instruction":
            args["instruction"], index = _next_value(tokens, index, token)
        elif token == "--challenge":
            args["challenge"], index = _next_value(tokens, index, token)
        elif token.startswith("--"):
            raise ValueError(f"Unknown /icr run option: {token}")
        else:
            positionals.append(token)
        index += 1

    text = " ".join(positionals).strip()
    if mode == "agentic_refinement":
        args.setdefault("content", text)
    else:
        args.setdefault("challenge", text)
    return args


def _next_value(tokens: list[str], index: int, option: str) -> tuple[str, int]:
    next_index = index + 1
    if next_index >= len(tokens):
        raise ValueError(f"{option} requires a value")
    return tokens[next_index], next_index
