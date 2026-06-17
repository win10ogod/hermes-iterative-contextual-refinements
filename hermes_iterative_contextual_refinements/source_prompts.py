"""Load original ICR prompt resources copied from the source project."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from typing import Any


SOURCE_PROMPT_SHA256 = {
    "DeepthinkPrompts.ts": "6c8702fd9a6d5fb9abe5a53fb2234e1fba484fceb03170b19b46014d1da44652",
    "ContextualPrompts.ts": "45e88e5fff36e705432f02e3d4023bfe948fb6da5b83b7e03c148ddff6580f50",
    "AdaptiveDeepthinkPrompt.ts": "26e66bb46e78915405419412fa953f59203dd9590fa9589b08c2619677b696be",
    "AgenticModePrompt.ts": "b8afbbe77881c86e3d3e40dbfe3a3e3922454dbf18fdb2f74d5a746f0eef437e",
    "DCAPrompts.ts": "8ae9351a923be9e7930b1f1b95d6568ddb986e0e634936c93c0b75db602c8638",
}


DEEPTHINK_ROLE_TO_SOURCE_KEY = {
    "initial_strategy": "sys_deepthink_initialStrategy",
    "sub_strategy": "sys_deepthink_subStrategy",
    "hypothesis_generation": "sys_deepthink_hypothesisGeneration",
    "hypothesis_testing": "sys_deepthink_hypothesisTester",
    "solution_attempt": "sys_deepthink_solutionAttempt",
    "solution_critique": "sys_deepthink_solutionCritique",
    "dissected_synthesis": "sys_deepthink_dissectedSynthesis",
    "self_improvement": "sys_deepthink_selfImprovement",
    "structured_solution_pool": "sys_deepthink_structuredSolutionPool",
    "memory_bank": "sys_deepthink_memoryBank",
    "post_quality_filter": "sys_deepthink_postQualityFilter",
    "strategy_update": "sys_deepthink_initialStrategy",
    "final_judge": "sys_deepthink_finalJudge",
}


def deepthink_system_prompt(role: str) -> str:
    return load_deepthink_prompts()[DEEPTHINK_ROLE_TO_SOURCE_KEY[role]]


@lru_cache(maxsize=1)
def load_deepthink_prompts() -> dict[str, str]:
    text = _resource_text("DeepthinkPrompts.ts")
    constants = {
        "DeepthinkContext": _extract_const_template(text, "DeepthinkContext"),
        "systemInstructionJsonOutputOnly": _extract_const_template(text, "systemInstructionJsonOutputOnly"),
    }
    keys = set(DEEPTHINK_ROLE_TO_SOURCE_KEY.values())
    return {key: _interpolate(_extract_object_template(text, key), constants) for key in sorted(keys)}


@lru_cache(maxsize=1)
def load_contextual_prompts() -> dict[str, str]:
    text = _resource_text("ContextualPrompts.ts")
    return {
        "main_generator": _extract_const_template(text, "MAIN_GENERATOR_SYSTEM_PROMPT"),
        "iterative_agent": _extract_const_template(text, "ITERATIVE_AGENT_SYSTEM_PROMPT"),
        "strategic_pool_agent": _extract_const_template(text, "STRATEGIC_POOL_AGENT_SYSTEM_PROMPT"),
        "memory_agent": _extract_const_template(text, "MEMORY_AGENT_SYSTEM_PROMPT"),
    }


@lru_cache(maxsize=1)
def load_adaptive_prompts() -> dict[str, str]:
    text = _resource_text("AdaptiveDeepthinkPrompt.ts")
    deepthink = load_deepthink_prompts()
    return {
        "main": _extract_const_template(text, "ADAPTIVE_DEEPTHINK_SYSTEM_PROMPT"),
        "strategy_generation": deepthink["sys_deepthink_initialStrategy"],
        "hypothesis_generation": deepthink["sys_deepthink_hypothesisGeneration"],
        "hypothesis_testing": deepthink["sys_deepthink_hypothesisTester"],
        "execution": deepthink["sys_deepthink_solutionAttempt"],
        "solution_critique": deepthink["sys_deepthink_solutionCritique"],
        "corrector": deepthink["sys_deepthink_selfImprovement"],
        "final_judge": deepthink["sys_deepthink_finalJudge"],
    }


@lru_cache(maxsize=1)
def load_agentic_prompts() -> dict[str, str]:
    text = _resource_text("AgenticModePrompt.ts")
    return {
        "agentic_system": _extract_const_template(text, "AGENTIC_SYSTEM_PROMPT").strip(),
        "verifier_system": _extract_const_template(text, "VERIFIER_SYSTEM_PROMPT").strip(),
    }


@lru_cache(maxsize=1)
def load_dca_prompts() -> dict[str, str]:
    text = _resource_text("DCAPrompts.ts")
    return {
        "pool_generator": _extract_object_template(text, "sys_pool_generator"),
        "local_pool_agent": _extract_object_template(text, "sys_local_pool_agent"),
    }


def _resource_text(name: str) -> str:
    return (resources.files(__package__) / "source_prompts" / name).read_text(encoding="utf-8")


def _extract_const_template(text: str, const_name: str) -> str:
    match = re.search(rf"(?:export\s+)?const\s+{re.escape(const_name)}\s*=\s*`", text)
    if not match:
        raise KeyError(f"Template constant not found: {const_name}")
    return _read_template_literal(text, match.end() - 1)


def _extract_object_template(text: str, key: str) -> str:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*`", text)
    if not match:
        raise KeyError(f"Template property not found: {key}")
    return _read_template_literal(text, match.end() - 1)


def _read_template_literal(text: str, tick_index: int) -> str:
    if text[tick_index] != "`":
        raise ValueError("tick_index must point at a template-literal backtick")
    chars: list[str] = []
    index = tick_index + 1
    while index < len(text):
        char = text[index]
        if char == "`":
            return "".join(chars)
        if char == "\\":
            chars.append(_decode_escape(text, index))
            index += _escape_width(text, index)
            continue
        if char == "$" and index + 1 < len(text) and text[index + 1] == "{":
            end = text.find("}", index + 2)
            if end == -1:
                raise ValueError("Unterminated template interpolation")
            chars.append(text[index : end + 1])
            index = end + 1
            continue
        chars.append(char)
        index += 1
    raise ValueError("Unterminated template literal")


def _decode_escape(text: str, index: int) -> str:
    if index + 1 >= len(text):
        return "\\"
    nxt = text[index + 1]
    if nxt == "n":
        return "\n"
    if nxt == "r":
        return "\r"
    if nxt == "t":
        return "\t"
    if nxt in {"`", "\\", "$"}:
        return nxt
    return nxt


def _escape_width(text: str, index: int) -> int:
    return 2 if index + 1 < len(text) else 1


def _interpolate(template: str, values: dict[str, Any]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("${" + key + "}", str(value))
    unresolved = re.findall(r"\$\{([^}]+)\}", result)
    if unresolved:
        raise ValueError(f"Unresolved prompt interpolation(s): {', '.join(sorted(set(unresolved)))}")
    return result
