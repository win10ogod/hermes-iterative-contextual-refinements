"""Prompt parity checks for installed Hermes ICR packages."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Any

from . import adaptive, agentic, contextual, dca, prompts
from .source_prompts import (
    DEEPTHINK_ROLE_TO_SOURCE_KEY,
    SOURCE_PROMPT_SHA256,
    load_adaptive_prompts,
    load_agentic_prompts,
    load_contextual_prompts,
    load_dca_prompts,
    load_deepthink_prompts,
)


class PromptParityError(RuntimeError):
    """Raised when bundled source prompts or runtime wiring drift."""


def collect_prompt_parity_report() -> dict[str, Any]:
    failures: list[str] = []
    resource_digests: dict[str, str] = {}

    source_dir = resources.files(__package__) / "source_prompts"
    for name, expected in SOURCE_PROMPT_SHA256.items():
        path = source_dir / name
        if not path.is_file():
            failures.append(f"missing source prompt resource: {name}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        resource_digests[name] = digest
        if digest != expected:
            failures.append(f"checksum mismatch for {name}: expected {expected}, got {digest}")

    deepthink = load_deepthink_prompts()
    for role, source_key in DEEPTHINK_ROLE_TO_SOURCE_KEY.items():
        if prompts.system_prompt(role) != deepthink[source_key]:
            failures.append(f"Deepthink system prompt drift for role {role}")

    contextual_prompts = load_contextual_prompts()
    if contextual.MAIN_GENERATOR_PROMPT != contextual_prompts["main_generator"]:
        failures.append("contextual main-generator system prompt drift")
    if contextual.ITERATIVE_AGENT_PROMPT != contextual_prompts["iterative_agent"]:
        failures.append("contextual iterative-agent system prompt drift")
    if contextual.STRATEGIC_POOL_PROMPT != contextual_prompts["strategic_pool_agent"]:
        failures.append("contextual strategic-pool system prompt drift")
    if contextual.MEMORY_AGENT_PROMPT != contextual_prompts["memory_agent"]:
        failures.append("contextual memory-agent system prompt drift")

    adaptive_prompts = load_adaptive_prompts()
    if adaptive.ADAPTIVE_ORCHESTRATOR_PROMPT != adaptive_prompts["main"]:
        failures.append("adaptive orchestrator system prompt drift")

    agentic_prompts = load_agentic_prompts()
    if agentic.AGENTIC_SYSTEM_PROMPT != agentic_prompts["agentic_system"]:
        failures.append("agentic system prompt drift")
    if agentic.VERIFIER_SYSTEM_PROMPT != agentic_prompts["verifier_system"]:
        failures.append("agentic verifier system prompt drift")

    dca_prompts = load_dca_prompts()
    if dca.POOL_GENERATOR_PROMPT != dca_prompts["pool_generator"]:
        failures.append("DCA pool-generator system prompt drift")
    if dca.LOCAL_POOL_PROMPT != dca_prompts["local_pool_agent"]:
        failures.append("DCA local-pool system prompt drift")

    builder_fragments = {
        "initial_strategy": (
            prompts.strategy_generation_prompt("Task", 3),
            ["<Initial Strategy Generation Request>", "genuinely novel, fundamentally distinct", "Return only JSON"],
        ),
        "hypothesis_generation": (
            prompts.hypothesis_generation_prompt("Task", 2, "selective_injection", "<Strategy id=\"main1\">A</Strategy>"),
            ['"target_strategies" as an array of strategy IDs', "<Hypothesis Generation Request>"],
        ),
        "execution": (
            prompts.execution_prompt(
                "Task",
                {
                    "id": "main1",
                    "main_strategy_id": "main1",
                    "main_strategy_text": "Strategy",
                    "sub_strategy_text": "Sub",
                    "branch_version": 1,
                },
                [{"id": "main1", "text": "Strategy"}, {"id": "main2", "text": "Other"}],
                "<Packet />",
            ),
            ["<Assigned Strategy Text>", "<Execution Request>", "<Relevant Context For Your Current Strategy>"],
        ),
        "final_judge": (
            prompts.final_judge_prompt(
                "Task",
                [
                    {"id": "main1", "main_strategy_id": "main1", "sub_strategy_text": "Sub", "solution": "A"},
                    {"id": "main2", "main_strategy_id": "main2", "sub_strategy_text": "Sub", "solution": "B"},
                ],
            ),
            ["Original Challenge:", "<SOLUTION_1>", '"best_solution_id"'],
        ),
        "solution_pool": (
            prompts.solution_pool_prompt(
                "Task",
                {"id": "main1", "main_strategy_text": "Strategy", "branch_version": 1, "branch_iteration_count": 1},
                [{"id": "main1", "main_strategy_text": "Strategy"}, {"id": "main2", "main_strategy_text": "Other"}],
                "<Packet />",
                1,
            ),
            ["<Solution Pool Request>", "<Strategy-Aware Selective Knowledge Packet>", "pool-generation anchor"],
        ),
    }
    for builder, (text, fragments) in builder_fragments.items():
        for fragment in fragments:
            if fragment not in text:
                failures.append(f"prompt builder {builder} missing fragment: {fragment}")

    return {
        "ok": not failures,
        "failures": failures,
        "resource_digests": resource_digests,
        "checked_resources": sorted(SOURCE_PROMPT_SHA256),
        "checked_deepthink_roles": sorted(DEEPTHINK_ROLE_TO_SOURCE_KEY),
    }


def validate_prompt_parity() -> dict[str, Any]:
    report = collect_prompt_parity_report()
    if not report["ok"]:
        raise PromptParityError("; ".join(report["failures"]))
    return report


def main() -> int:
    report = collect_prompt_parity_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
