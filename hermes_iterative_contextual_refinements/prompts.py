"""Prompt builders that preserve ICR role boundaries."""

from __future__ import annotations

from typing import Any

from .json_utils import dumps


JSON_ONLY = (
    "Return only a single valid JSON object. Do not include prose, markdown fences, "
    "or extra keys unless the schema allows them."
)


DEEPTHINK_CONTEXT = """
Deepthink is a multi-agent search and refinement system. Strategies are branch
identities, not steps. Agents receive only curated context for their role.
Final judging compares candidate solutions only and must not inspect internal
critiques, memory banks, PQF decisions, solution pools, hypothesis routing, or
replacement history.
""".strip()


ROLE_PROMPTS = {
    "initial_strategy": (
        "You are the Initial Strategy Generation Agent. Generate independent, "
        "domain-adapted branch-level strategies. Do not solve the challenge."
    ),
    "sub_strategy": (
        "You are the Sub-Strategy Generation Agent. Generate narrower independent "
        "lenses inside the assigned main strategy. Do not solve the challenge."
    ),
    "hypothesis_generation": (
        "You are the Hypothesis Generation Agent. Generate testable hypotheses, "
        "not final answers. In selective mode, include target strategy ids."
    ),
    "hypothesis_testing": (
        "You are the Hypothesis Testing Agent. Test exactly one hypothesis. "
        "Attempt validation and refutation, then classify VALIDATED, REFUTED, or INCONCLUSIVE."
    ),
    "solution_attempt": (
        "You are the Solution Attempt Agent. Execute the assigned strategy faithfully "
        "and produce a complete work product."
    ),
    "solution_critique": (
        "You are the Solution Critique Agent. Identify flaws, gaps, unjustified claims, "
        "counterexamples, and strategy-fidelity issues. Do not fix the solution."
    ),
    "self_improvement": (
        "You are the Self-Improvement Agent. Produce a corrected complete solution "
        "that addresses the critique while preserving the assigned strategy."
    ),
    "dissected_synthesis": (
        "You are the Dissected Observations Synthesis Agent. Consolidate critique "
        "findings into reusable diagnostic context. Do not produce final answers."
    ),
    "structured_solution_pool": (
        "You are the Structured Solution Pool Agent. Generate exactly five substantive "
        "alternatives, artifacts, tests, or reusable blocks for the assigned branch."
    ),
    "memory_bank": (
        "You are the Memory Bank Agent. Distill branch exploration lessons into "
        "validated invariants, dead ends, flaws, techniques, refuted assumptions, "
        "open questions, and guidance. Do not summarize solution prose."
    ),
    "post_quality_filter": (
        "You are the Post Quality Filter Agent. Decide whether assigned strategy slots "
        "should keep their strategy or update the branch strategy. Do not rank final solutions."
    ),
    "strategy_update": (
        "You are the Strategy Update Generator. Generate replacement strategy text "
        "for slots marked update, avoiding failed prior directions."
    ),
    "final_judge": (
        "You are the Final Judge. Compare only candidate solution texts and select "
        "the best final answer. Ignore internal process signals."
    ),
}


def system_prompt(role: str) -> str:
    return f"{ROLE_PROMPTS[role]}\n\n{DEEPTHINK_CONTEXT}"


def strategy_generation_prompt(challenge: str, count: int) -> str:
    return f"""Core Challenge:
{challenge}

Generate exactly {count} genuinely distinct high-level strategic interpretations.
Each strategy must be self-contained and useful as a branch identity.
Do not solve the challenge.

Return JSON:
{{"strategies": ["Strategy 1: ..."]}}"""


def sub_strategy_prompt(challenge: str, current: dict[str, Any], all_strategies: list[dict[str, Any]], count: int) -> str:
    others = "\n\n".join(f"{s['id']}: {s['text']}" for s in all_strategies if s["id"] != current["id"])
    return f"""Core Challenge:
{challenge}

<Assigned Main Strategy id="{current['id']}">
{current['text']}
</Assigned Main Strategy>

<Other Main Strategies For Awareness>
{others or 'No other strategies.'}
</Other Main Strategies For Awareness>

Generate exactly {count} narrower independent sub-strategy interpretations.
Return JSON:
{{"sub_strategies": ["Sub-strategy 1: ..."]}}"""


def hypothesis_generation_prompt(challenge: str, count: int, mode: str, strategy_context: str, previous: str = "") -> str:
    mapping = (
        'Each hypothesis must include "target_strategies" as an array of main strategy ids. '
        "Use an empty array only for globally useful hypotheses."
        if mode == "selective_injection"
        else "Hypotheses may be globally useful and do not need strategy mappings."
    )
    return f"""Core Challenge:
{challenge}

<Current Strategies>
{strategy_context or 'Strategy context is not provided for this hypothesis mode.'}
</Current Strategies>

<Previous Hypothesis Context>
{previous or 'No previous hypothesis rounds.'}
</Previous Hypothesis Context>

Generate exactly {count} hypotheses to investigate before execution.
Do not solve the challenge. {mapping}

Return JSON:
{{"hypotheses": [{{"text": "Hypothesis text", "target_strategies": ["main1"]}}]}}"""


def hypothesis_test_prompt(challenge: str, hypothesis: dict[str, Any]) -> str:
    return f"""Core Challenge:
{challenge}

<Hypothesis To Test id="{hypothesis['id']}">
{hypothesis['text']}
</Hypothesis To Test>

Test only this hypothesis. Do not use strategy context. Attempt validation and refutation.
End with one classification: VALIDATED, REFUTED, or INCONCLUSIVE."""


def information_packet(hypotheses: list[dict[str, Any]], tests: dict[str, str]) -> str:
    if not hypotheses:
        return "<Full Information Packet>No hypotheses requested.</Full Information Packet>"
    entries = []
    for index, hyp in enumerate(hypotheses, 1):
        targets = hyp.get("target_strategy_ids") or []
        target_text = ", ".join(targets) if targets else "all"
        entries.append(
            f"""<Hypothesis {index}>
ID: {hyp['id']}
Target Strategies: {target_text}
Hypothesis: {hyp['text']}
Hypothesis Testing: {tests.get(hyp['id'], 'Not tested.')}
</Hypothesis {index}>"""
        )
    return "<Full Information Packet>\n" + "\n\n".join(entries) + "\n</Full Information Packet>"


def strategy_specific_packets(strategies: list[dict[str, Any]], hypotheses: list[dict[str, Any]], tests: dict[str, str]) -> dict[str, str]:
    packets: dict[str, str] = {}
    for strategy in strategies:
        selected = [
            hyp
            for hyp in hypotheses
            if not hyp.get("target_strategy_ids") or strategy["id"] in hyp.get("target_strategy_ids", [])
        ]
        packets[strategy["id"]] = information_packet(selected, tests)
    return packets


def execution_prompt(challenge: str, branch: dict[str, Any], all_strategies: list[dict[str, Any]], packet: str) -> str:
    others = "\n\n".join(f"{s['id']}: {s['text']}" for s in all_strategies if s["id"] != branch["main_strategy_id"])
    return f"""Core Challenge:
{challenge}

<Assigned Main Strategy id="{branch['main_strategy_id']}">
{branch['main_strategy_text']}
</Assigned Main Strategy>

<Assigned Sub Strategy id="{branch['id']}">
{branch['sub_strategy_text']}
</Assigned Sub Strategy>

<Other Main Strategies For Awareness>
{others or 'No other main strategies.'}
</Other Main Strategies For Awareness>

{packet}

Execute the assigned branch faithfully and completely."""


def critique_prompt(challenge: str, branch: dict[str, Any], solution: str, history: list[dict[str, Any]] | None = None) -> str:
    recent = dumps((history or [])[-5:])
    return f"""Core Challenge:
{challenge}

<Assigned Strategy id="{branch['main_strategy_id']}" branchVersion="{branch.get('branch_version', 1)}">
{branch['main_strategy_text']}
</Assigned Strategy>

<Critique Target>
{solution}
</Critique Target>

<Recent Branch History>
{recent}
</Recent Branch History>

Critique the target solution only. Verify strategy fidelity first, then execution quality.
Do not suggest fixes."""


def correction_prompt(
    challenge: str,
    branch: dict[str, Any],
    solution: str,
    critique: str,
    synthesis: str = "",
    full_context: str = "",
    repository: str = "",
    packet: str = "",
    global_iteration: int | None = None,
    branch_iteration: int | None = None,
) -> str:
    iter_context = ""
    if global_iteration is not None:
        iter_context = f"""<EvolvingDepthFirstSearchCorrectionContext>
Global iteration: {global_iteration}
Assigned strategy: {branch['main_strategy_id']}
Assigned branch version: {branch.get('branch_version', 1)}
Assigned branch-local iteration to produce: {branch_iteration}
</EvolvingDepthFirstSearchCorrectionContext>"""
    return f"""Core Challenge:
{challenge}

<Assigned Strategy>
{branch['main_strategy_text']}
</Assigned Strategy>

{iter_context}

<Previous Solution Attempt>
{solution}
</Previous Solution Attempt>

<Critique>
{critique}
</Critique>

<Shared Critique Synthesis>
{synthesis or 'Not available.'}
</Shared Critique Synthesis>

<Full Solution Context>
{full_context or 'Not available.'}
</Full Solution Context>

<Strategy-Aware Selective Knowledge Packet>
{packet or 'Not available.'}
</Strategy-Aware Selective Knowledge Packet>

<Curated Evolving DFS Repository>
{repository or 'Not available.'}
</Curated Evolving DFS Repository>

Produce the next corrected complete solution. Work inside the assigned strategy only."""


def synthesis_prompt(challenge: str, branches: list[dict[str, Any]], packet: str = "") -> str:
    lines = []
    for branch in branches:
        lines.append(
            f"""<Candidate id="{branch['id']}">
<MainStrategy>{branch['main_strategy_text']}</MainStrategy>
<SubStrategy>{branch['sub_strategy_text']}</SubStrategy>
<OriginalSolution>{branch.get('solution', '')}</OriginalSolution>
<Critique>{branch.get('critique', '')}</Critique>
</Candidate>"""
        )
    return f"""Core Challenge:
{challenge}

<Original Solutions And Critiques>
{chr(10).join(lines)}
</Original Solutions And Critiques>

<Hypothesis Packet>
{packet or 'Not included.'}
</Hypothesis Packet>

Consolidate recurring failures, domain-specific problems, assumptions, missing elements,
and conflicts between critiques. Do not produce corrected solutions."""


def full_solution_context(branches: list[dict[str, Any]], assigned_id: str) -> str:
    lines = []
    for branch in branches:
        lines.append(
            f"""<Candidate id="{branch['id']}" assigned="{str(branch['id'] == assigned_id).lower()}">
<MainStrategy>{branch['main_strategy_text']}</MainStrategy>
<SubStrategy>{branch['sub_strategy_text']}</SubStrategy>
<OriginalSolution>{branch.get('solution', '')}</OriginalSolution>
<Critique>{branch.get('critique', '')}</Critique>
</Candidate>"""
        )
    return "\n\n".join(lines)


def final_judge_prompt(challenge: str, candidates: list[dict[str, Any]]) -> str:
    candidate_text = "\n\n".join(
        f"""<Candidate id="{candidate['id']}" mainStrategyId="{candidate['main_strategy_id']}" subStrategy="{candidate['sub_strategy_text']}">
{candidate['solution']}
</Candidate>"""
        for candidate in candidates
    )
    return f"""Core Challenge:
{challenge}

<Candidate Solutions>
{candidate_text}
</Candidate Solutions>

Select the best solution. Compare only the candidate solution texts above."""


def format_branch_history(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "No branch correction/critique history is available yet."
    blocks = []
    for entry in entries:
        blocks.append(
            f"""<Iteration global="{entry['global_iteration']}" branch="{entry['branch_iteration']}" branchVersion="{entry.get('branch_version', 1)}" label="{entry.get('label', '')}">
<SolutionOrCorrection>
{entry.get('solution', '')}
</SolutionOrCorrection>
<Critique>
{entry.get('critique', '')}
</Critique>
</Iteration>"""
        )
    return "\n\n".join(blocks)


def format_pool_history(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "No previous solution pool output is available for this strategy yet."
    return "\n\n".join(
        f"""<SolutionPoolOutput global="{entry['global_iteration']}" branch="{entry['branch_iteration']}">
{entry.get('pool_response', '')}
</SolutionPoolOutput>"""
        for entry in entries
    )


def correction_repository(current: dict[str, Any], all_branches: list[dict[str, Any]], max_history: int = 5) -> str:
    other = []
    for branch in all_branches:
        if branch["id"] == current["id"]:
            continue
        other.append(
            f"""<Strategy-{branch['id']} branchVersion="{branch.get('branch_version', 1)}">
<StrategyText>{branch['main_strategy_text']}</StrategyText>
<LatestCorrectionOrExecution>{branch.get('latest_solution', '')}</LatestCorrectionOrExecution>
<LatestCritique>{branch.get('latest_critique', '')}</LatestCritique>
</Strategy-{branch['id']}>"""
        )
    current_block = f"""<Strategy-{current['id']} branchVersion="{current.get('branch_version', 1)}" assigned="true">
<StrategyText>{current['main_strategy_text']}</StrategyText>
<MemoryBank>{current.get('memory_bank') or 'Not available.'}</MemoryBank>
<LatestCorrectionOrExecution>{current.get('latest_solution', '')}</LatestCorrectionOrExecution>
<LatestCritique>{current.get('latest_critique', '')}</LatestCritique>
<BranchHistory last="{max_history}">
{format_branch_history(current.get('history', [])[-max_history:])}
</BranchHistory>
<LatestStrategySolutionPool>{current.get('latest_pool') or 'Not available.'}</LatestStrategySolutionPool>
</Strategy-{current['id']}>"""
    return f"""<Context From Other Strategies>
{chr(10).join(other) if other else 'No other strategy context is available.'}
</Context From Other Strategies>

<Relevant Context For Your Current Strategy>
{current_block}
</Relevant Context For Your Current Strategy>"""


def solution_pool_prompt(challenge: str, current: dict[str, Any], all_branches: list[dict[str, Any]], packet: str, global_iteration: int) -> str:
    other = []
    for branch in all_branches:
        if branch["id"] == current["id"]:
            continue
        other.append(
            f"""<Strategy-{branch['id']} branchVersion="{branch.get('branch_version', 1)}">
<StrategyText>{branch['main_strategy_text']}</StrategyText>
<LatestSolutionPool>{branch.get('latest_pool') or 'Not available.'}</LatestSolutionPool>
</Strategy-{branch['id']}>"""
        )
    current_block = f"""<Strategy-{current['id']} branchVersion="{current.get('branch_version', 1)}" assigned="true">
<StrategyText>{current['main_strategy_text']}</StrategyText>
<MemoryBank>{current.get('memory_bank') or 'Not available.'}</MemoryBank>
<LatestCorrectionOrExecution>{current.get('latest_solution', '')}</LatestCorrectionOrExecution>
<LatestCritique>{current.get('latest_critique', '')}</LatestCritique>
<PoolHistory last="5">
{format_pool_history(current.get('pool_history', [])[-5:])}
</PoolHistory>
</Strategy-{current['id']}>"""
    return f"""Core Challenge:
{challenge}

<EvolvingDepthFirstSearchSolutionPoolContext>
Global iteration: {global_iteration}
Assigned strategy: {current['id']}
Assigned branch version: {current.get('branch_version', 1)}
Current branch-local iteration: {current.get('branch_iteration_count', 1)}
</EvolvingDepthFirstSearchSolutionPoolContext>

<Context From Other Strategies>
{chr(10).join(other) if other else 'No other strategy solution-pool context is available.'}
</Context From Other Strategies>

<Strategy-Aware Selective Knowledge Packet>
{packet or 'Not available.'}
</Strategy-Aware Selective Knowledge Packet>

<Relevant Context For Your Current Strategy>
{current_block}
</Relevant Context For Your Current Strategy>

Generate exactly five solution-pool entries. Return JSON with a "solutions" array."""


def memory_prompt(challenge: str, branch: dict[str, Any], window: list[dict[str, Any]], start: int, end: int) -> str:
    return f"""Core Challenge:
{challenge}

<Strategy id="{branch['id']}" branchVersion="{branch.get('branch_version', 1)}">
{branch['main_strategy_text']}
</Strategy>

<Previous Memory Bank>
{branch.get('memory_bank') or 'Not available.'}
</Previous Memory Bank>

<Raw Branch History To Distill branchIterations="{start}-{end}">
{format_branch_history(window)}
</Raw Branch History To Distill>

Create one unified memory bank for this strategy branch. If a previous memory bank
exists, recursively merge it with the new raw history so earlier lessons are not lost."""


def pqf_prompt(challenge: str, group_index: int, group_count: int, group: list[dict[str, Any]], all_branches: list[dict[str, Any]], aggressiveness: str) -> str:
    all_active = "\n\n".join(f"{b['id']}: {b['main_strategy_text']}" for b in all_branches)
    sections = []
    for branch in group:
        sections.append(
            f"""<StrategyForDecision id="{branch['id']}" branchVersion="{branch.get('branch_version', 1)}">
<StrategyText>{branch['main_strategy_text']}</StrategyText>
<FullRecentCorrectionCritiqueHistory>
{format_branch_history(branch.get('history', [])[-5:])}
</FullRecentCorrectionCritiqueHistory>
</StrategyForDecision>"""
        )
    return f"""Core Challenge:
{challenge}

<PQFAggressiveness>{aggressiveness}</PQFAggressiveness>

<All Active Strategies For Awareness>
{all_active}
</All Active Strategies For Awareness>

<PQF Group group="{group_index + 1}" totalGroups="{group_count}">
Evaluate only the strategies inside this group. You see full recent correction/critique
history for these strategies only.
{chr(10).join(sections)}
</PQF Group>

Return JSON:
{{"analysis_summary":"short summary","strategies":[{{"strategy_id":"main1","decision":"keep","reasoning":"..."}}]}}

Decision must be exactly "keep" or "update"."""


def strategy_update_prompt(challenge: str, decisions: list[dict[str, Any]], all_branches: list[dict[str, Any]], archives: list[dict[str, Any]]) -> str:
    failed_context = []
    for decision in decisions:
        if decision.get("decision") != "update":
            continue
        branch = next(b for b in all_branches if b["id"] == decision["strategy_id"])
        failed_context.append(
            f"""<UpdateRequest strategyId="{branch['id']}">
<Old Strategy Text>{branch['main_strategy_text']}</Old Strategy Text>
<PQF Reasoning>{decision.get('reasoning', '')}</PQF Reasoning>
<Latest Correction Or Execution>{branch.get('latest_solution', '')}</Latest Correction Or Execution>
<Latest Critique>{branch.get('latest_critique', '')}</Latest Critique>
<Memory Bank>{branch.get('memory_bank') or 'Not available.'}</Memory Bank>
</UpdateRequest>"""
        )
    previous = "\n\n".join(
        f"{a['strategy_id']} (v{a['previous_branch_version']}): {a['previous_strategy_text']}"
        for a in archives
    ) or "No prior replaced strategies yet."
    return f"""Core Challenge:
{challenge}

<Consolidated PQF Decision Vector>
{dumps(decisions)}
</Consolidated PQF Decision Vector>

<Current Active Strategies>
{chr(10).join(f"{b['id']} (v{b.get('branch_version', 1)}): {b['main_strategy_text']}" for b in all_branches)}
</Current Active Strategies>

<Previously Replaced Strategies To Avoid Repeating>
{previous}
</Previously Replaced Strategies To Avoid Repeating>

<Failed Strategy Context For Updates>
{chr(10).join(failed_context)}
</Failed Strategy Context For Updates>

Generate exactly one replacement strategy for every strategy marked update.
Return JSON:
{{"strategies":[{{"strategy_id":"main1","strategy":"Replacement strategy text"}}]}}"""


def hypothesis_refresh_prompt(
    challenge: str,
    count: int,
    completed_global_iteration: int,
    previous_rounds: list[dict[str, Any]],
    current_branches: list[dict[str, Any]],
    updated_strategy_ids: list[str],
) -> str:
    strategies = []
    for branch in current_branches:
        strategies.append(
            f"""<Strategy id="{branch['id']}" branchVersion="{branch.get('branch_version', 1)}">
<StrategyText>{branch['main_strategy_text']}</StrategyText>
<LastTwoCorrectionCritiquePairs>
{format_branch_history(branch.get('history', [])[-2:])}
</LastTwoCorrectionCritiquePairs>
</Strategy>"""
        )
    update_note = (
        f"Strategies recently updated and needing fresh targeted hypotheses: {', '.join(updated_strategy_ids)}."
        if updated_strategy_ids
        else "No strategies were recently updated."
    )
    return f"""Core Challenge:
{challenge}

<Hypothesis Heartbeat>
Completed global iteration: {completed_global_iteration}
Generate exactly {count} new or updated hypotheses.
Mode: selective, strategy-aware routing only.
</Hypothesis Heartbeat>

<Previous Hypotheses And Testing Packets>
{dumps(previous_rounds)}
</Previous Hypotheses And Testing Packets>

<Current Active Strategies And Last Two Histories>
{chr(10).join(strategies)}
</Current Active Strategies And Last Two Histories>

<Strategy Update Note>
{update_note}
</Strategy Update Note>

Return JSON:
{{"hypotheses":[{{"text":"Hypothesis text","target_strategies":["main1"]}}]}}"""

