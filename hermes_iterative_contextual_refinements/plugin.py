"""Hermes plugin registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .commands import make_icr_command
from .constants import TOOLSET_NAME
from .schemas import icr_export_schema, icr_list_runs_schema, icr_run_schema, icr_start_schema, icr_status_schema
from .tools import make_handlers


def register(ctx: Any) -> None:
    handlers = make_handlers(ctx)
    ctx.register_tool(
        name="icr_run",
        toolset=TOOLSET_NAME,
        schema=icr_run_schema(),
        handler=handlers["icr_run"],
        description="Run ICR modes through Hermes-owned LLM access.",
    )
    ctx.register_tool(
        name="icr_start",
        toolset=TOOLSET_NAME,
        schema=icr_start_schema(),
        handler=handlers["icr_start"],
        description="Start ICR in the background and poll progress with icr_status.",
    )
    ctx.register_tool(
        name="icr_status",
        toolset=TOOLSET_NAME,
        schema=icr_status_schema(),
        handler=handlers["icr_status"],
        description="Inspect an ICR run status and metadata.",
    )
    ctx.register_tool(
        name="icr_export",
        toolset=TOOLSET_NAME,
        schema=icr_export_schema(),
        handler=handlers["icr_export"],
        description="Export an ICR run as JSON or Markdown.",
    )
    ctx.register_tool(
        name="icr_list_runs",
        toolset=TOOLSET_NAME,
        schema=icr_list_runs_schema(),
        handler=handlers["icr_list_runs"],
        description="List recent ICR runs.",
    )
    ctx.register_command(
        name="icr",
        handler=make_icr_command(ctx),
        description="Run and inspect Iterative Contextual Refinements.",
        args_hint="run <mode> <challenge> | start <mode> <challenge> | status <run_id> | export <run_id> [json|markdown] | list [limit] | doctor [--platform cli]",
    )
    _register_skills(ctx)


def _register_skills(ctx: Any) -> None:
    base = Path(__file__).resolve().parent / "skills"
    skill_descriptions = {
        "icr-runner": "Run ICR modes through Hermes tools and inspect saved artifacts.",
        "icr-deepthink": "Use Deepthink single-pass and Evolving DFS modes correctly.",
        "icr-contextual-refinement": "Operate the contextual refinement loop with memory and strategic pool behavior.",
        "icr-agentic-refinement": "Operate agentic refinement with read/edit/verify/search/exit tool semantics.",
        "icr-results-review": "Review ICR artifacts, final judge boundaries, and exported run evidence.",
        "icr-prompt-parity": "Verify ICR prompt parity against bundled upstream prompt resources.",
        "icr-state-machine": "Inspect upstream-shaped React/LangGraph state machine artifacts and replay indexes.",
    }
    for name, description in skill_descriptions.items():
        ctx.register_skill(name, base / name / "SKILL.md", description)
