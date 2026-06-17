"""Prompt builders that preserve ICR role boundaries."""

from __future__ import annotations

from typing import Any

from .json_utils import dumps
from .source_prompts import deepthink_system_prompt


JSON_ONLY = (
    "Return only a single valid JSON object. Do not include prose, markdown fences, "
    "or extra keys unless the schema allows them."
)
SECTION_SEPARATOR = "-------------------------------------------------------------------------------"
REPOSITORY_CURRENT_CONTEXT_MARKER = "\n__DEEPTHINK_CURRENT_STRATEGY_CONTEXT__\n"


def system_prompt(role: str) -> str:
    return deepthink_system_prompt(role)


def strategy_generation_prompt(challenge: str, count: int) -> str:
    return f"""Core Challenge:
{challenge}

<Initial Strategy Generation Request>
Generate exactly {count} genuinely novel, fundamentally distinct high-level strategic interpretations for the Core Challenge.
Each strategy must be a single concise, information-dense paragraph.
Do not solve the challenge. Do not include final answers, conclusions, calculations, code, or detailed execution steps.
Return only JSON:
{{
  "strategies": [
    "Strategy 1: ..."
  ]
}}
</Initial Strategy Generation Request>"""


def sub_strategy_prompt(challenge: str, current: dict[str, Any], all_strategies: list[dict[str, Any]], count: int) -> str:
    others = "\n\n".join(f"{s['id']}: {s['text']}" for s in all_strategies if s["id"] != current["id"])
    return f"""Core Challenge:
{challenge}

<Assigned Main Strategy>
{current['text']}
</Assigned Main Strategy>

<Other Main Strategies For Awareness>
{others or 'No other strategies.'}
</Other Main Strategies For Awareness>

<Sub-Strategy Generation Request>
Generate exactly {count} genuinely distinct high-level sub-strategy interpretations within the assigned main strategy.
Do not solve the challenge. Do not output detailed execution plans.
Return only JSON:
{{
  "sub_strategies": [
    "Sub-strategy 1: ..."
  ]
}}
</Sub-Strategy Generation Request>"""


def hypothesis_generation_prompt(challenge: str, count: int, mode: str, strategy_context: str, previous: str = "") -> str:
    mapping = (
        'Each hypothesis must include "target_strategies" as an array of strategy IDs. '
        "Use an empty array only for globally useful hypotheses."
        if mode == "selective_injection"
        else "Hypotheses may be globally useful and do not need strategy mappings."
    )
    return f"""Core Challenge:
{challenge}

<Current Strategies>
{strategy_context or 'Strategy context is not required for this hypothesis mode.'}
</Current Strategies>

<Hypothesis Generation Request>
Generate exactly {count} hypotheses to investigate before execution.
Do not solve the Core Challenge and do not include final answers.
{mapping}
Return only JSON:
{{
  "hypotheses": [
    {{
      "text": "Hypothesis text",
      "target_strategies": ["main1"]
    }}
  ]
}}
</Hypothesis Generation Request>"""


def hypothesis_test_prompt(challenge: str, hypothesis: dict[str, Any]) -> str:
    return f"""Core Challenge:
{challenge}

<Assigned Hypothesis To Test>
{hypothesis['text']}
</Assigned Hypothesis To Test>

<Hypothesis Testing Request>
Investigate this hypothesis rigorously and independently. Attempt validation and refutation, test edge cases, and report only findings about the hypothesis.
Do not solve the Core Challenge unless the hypothesis explicitly requires checking a proposed answer.
</Hypothesis Testing Request>"""


def information_packet(hypotheses: list[dict[str, Any]], tests: dict[str, str]) -> str:
    if not hypotheses:
        return "<Full Information Packet>No hypotheses requested.</Full Information Packet>"
    entries = []
    for index, hyp in enumerate(hypotheses, 1):
        targets = hyp.get("target_strategy_ids") or []
        target_text = ", ".join(targets) if targets else "all"
        entries.append(
            f"""<Hypothesis {index}>
Hypothesis: {hyp['text']}
Target Strategies: {target_text}
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
        if selected:
            body = "\n\n".join(
                f"""<Hypothesis {hyp['id']}>
Hypothesis: {hyp['text']}
Hypothesis Testing: {tests.get(hyp['id'], 'No testing output available')}
</Hypothesis {hyp['id']}>"""
                for hyp in selected
            )
        else:
            body = "No active strategy-specific hypotheses are currently available for this strategy."
        packets[strategy["id"]] = (
            f"<Strategy-Specific Information Packet for Strategy {strategy['id']}>\n"
            f"{body}\n"
            f"</Strategy-Specific Information Packet for Strategy {strategy['id']}>"
        )
    return packets


def execution_prompt(challenge: str, branch: dict[str, Any], all_strategies: list[dict[str, Any]], packet: str) -> str:
    others = "\n\n".join(
        f"""<Strategy-{s['id']} branchVersion="{s.get('branch_version', 1)}">
{s['text']}
</Strategy-{s['id']}>"""
        for s in all_strategies
        if s["id"] != branch["main_strategy_id"]
    )
    branch_context = (
        f"""<BranchIdentity strategy="{branch['main_strategy_id']}" branchVersion="{branch.get('branch_version', 1)}" branchIterationCount="{branch.get('branch_iteration_count', 0)}" />"""
        if branch.get("branch_version")
        else "No prior branch-local execution context exists yet."
    )
    return f"""Core Challenge:
{challenge}

<Assigned Strategy Text>
{branch['main_strategy_text']}
</Assigned Strategy Text>

-------------------------------------------------------------------------------
<Context From Other Strategies>
{others or 'No cross-strategy context is available for this execution.'}
</Context From Other Strategies>

-------------------------------------------------------------------------------
<Strategy-Aware Selective Knowledge Packet>
{packet}
</Strategy-Aware Selective Knowledge Packet>

<Execution Request>
Execute the assigned framework completely and faithfully. Do not switch strategies. Produce the full solution attempt for this assigned framework.
</Execution Request>

-------------------------------------------------------------------------------
<Relevant Context For Your Current Strategy>
This is all the relevant context related to your current strategy. Treat this as your primary identity, constraint set, and final context anchor.

<Assigned Main Strategy>
{branch['main_strategy_text']}
</Assigned Main Strategy>

<Assigned Sub-Strategy Or Direct Strategy>
{branch['sub_strategy_text']}
</Assigned Sub-Strategy Or Direct Strategy>

{branch_context}
</Relevant Context For Your Current Strategy>"""


def critique_prompt(challenge: str, branch: dict[str, Any], solution: str, history: list[dict[str, Any]] | None = None) -> str:
    recent = dumps((history or [])[-5:])
    if history:
        return f"""Core Challenge:
{challenge}

<Assigned Strategy id="{branch['main_strategy_id']}" branchVersion="{branch.get('branch_version', 1)}">
{branch['main_strategy_text']}
</Assigned Strategy>

<Critique Target globalIteration="{branch.get('global_iteration', 0)}" branchIteration="{branch.get('branch_iteration_count', 1)}">
{solution}
</Critique Target>

<Recent Branch History>
{recent}
</Recent Branch History>

Your task is to critique the target solution only. Verify strategy fidelity first, then execution quality. Do not suggest fixes."""
    return f"""Core Challenge:
{challenge}

<Main Strategy>
{branch['main_strategy_text']}
</Main Strategy>

<Sub-Strategy id="{branch.get('id', branch['main_strategy_id'])}">
{branch.get('sub_strategy_text', branch['main_strategy_text'])}
</Sub-Strategy>

<Solution Attempt To Critique>
{solution}
</Solution Attempt To Critique>

<Critique Request>
Critique this solution attempt for correctness, rigor, completeness, strategy fidelity, and unresolved issues. Do not produce the corrected solution.
</Critique Request>"""


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
    if global_iteration is not None:
        repo = split_repository_context(repository or correction_repository(branch, [branch]))
        return f"""Core Challenge:
{challenge}

<Assigned Strategy Text>
{branch['main_strategy_text']}
</Assigned Strategy Text>

<EvolvingDepthFirstSearchCorrectionContext>
Global iteration: {global_iteration}
Assigned strategy: {branch['main_strategy_id']}
Assigned branch version: {branch.get('branch_version', 1)}
Assigned branch-local iteration to produce: {branch_iteration}
</EvolvingDepthFirstSearchCorrectionContext>

<Correction Request>
Produce the next corrected solution for the assigned strategy. Work inside the assigned strategy only. Use the current strategy's memory bank, branch history, latest critique, and latest solution pool when available. Other strategies are included only as latest correction plus latest critique for situational awareness.
</Correction Request>

{repo['other_context']}

{SECTION_SEPARATOR}
<Strategy-Aware Selective Knowledge Packet>
{packet or 'Not available.'}
</Strategy-Aware Selective Knowledge Packet>

{SECTION_SEPARATOR}
{repo['current_context']}"""
    solution_section = "".join(
        [
            critique or "No critique available.",
            f"\n\n<Dissected Observations Synthesis>\n{synthesis}\n</Dissected Observations Synthesis>" if synthesis else "",
            f"\n\n<All Solutions Context>\n{full_context}\n</All Solutions Context>" if full_context else "",
        ]
    )
    sub_strategy_text = branch.get("sub_strategy_text", branch["main_strategy_text"])
    return f"""Original Problem:
{challenge}

<Assigned Main Strategy>
{branch['main_strategy_text']}
</Assigned Main Strategy>

<Assigned Sub-Strategy>
{sub_strategy_text}
</Assigned Sub-Strategy>

<Original Solution Attempt>
{solution}
</Original Solution Attempt>

<Correction Context>
{solution_section}
</Correction Context>

<Self-Improvement Request>
Produce the corrected final solution for this assigned strategy/sub-strategy. Address the critique directly. Preserve strategy fidelity and output the full corrected solution.
</Self-Improvement Request>"""


def synthesis_prompt(challenge: str, branches: list[dict[str, Any]], packet: str = "") -> str:
    lines = []
    for branch in branches:
        lines.append(
            f"""<Strategy id="{branch['main_strategy_id']}">
{branch['main_strategy_text']}
<SubStrategy id="{branch['id']}">
{branch['sub_strategy_text']}
<SolutionAttempt>
{branch.get('solution', '')}
</SolutionAttempt>
<Critique>
{branch.get('critique', 'No critique available.')}
</Critique>
</SubStrategy>
</Strategy>"""
        )
    return f"""Original Problem:
{challenge}

<Information Packet>
{packet or 'Hypothesis exploration sharing is disabled for dissected observations.'}
</Information Packet>

<Solutions With Critiques>
{chr(10).join(lines) or 'No solution attempts available.'}
</Solutions With Critiques>

<Synthesis Request>
Synthesize the critiques into a concise, rigorous correction brief. Resolve conflicts by prioritizing the most concrete, logically supported critique. Do not solve from scratch.
</Synthesis Request>"""


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
        "\n".join(
            [
                f"<SOLUTION_{index + 1}>",
                f"ID: {candidate['id']}",
                f"Main Strategy: {candidate['main_strategy_id']}",
                f"Sub-Strategy: {candidate['sub_strategy_text']}",
                "Solution Text:",
                candidate["solution"],
                f"</SOLUTION_{index + 1}>",
            ]
        )
        for index, candidate in enumerate(candidates)
    )
    return f"""Original Challenge:
{challenge}

Below are {len(candidates)} candidate solutions from different strategic approaches. Select the single overall best solution.

Return JSON:
{{"best_solution_id":"ID of the winning solution","final_reasoning":"Detailed comparison based only on provided texts"}}

{candidate_text}
"""


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
    memory_block = (
        f"<MemoryBank For Strategy {current['id']}>\n{current.get('memory_bank')}\n</MemoryBank For Strategy {current['id']}>"
        if current.get("memory_bank")
        else ""
    )
    current_block = f"""<Strategy-{current['id']} branchVersion="{current.get('branch_version', 1)}" assigned="true">
<StrategyText>{current['main_strategy_text']}</StrategyText>
{memory_block}
<LatestCorrectionOrExecution>{current.get('latest_solution', '')}</LatestCorrectionOrExecution>
<LatestCritique>{current.get('latest_critique', '')}</LatestCritique>
<BranchHistory last="{max_history}">
{format_branch_history(current.get('history', [])[-max_history:])}
</BranchHistory>
<LatestStrategySolutionPool>{current.get('latest_pool') or 'Not available.'}</LatestStrategySolutionPool>
</Strategy-{current['id']}>"""
    return f"""<Context From Other Strategies For Cross-Learning, Synthesis, Gap Anticipation, Critique Anticipation, And Orthogonality>
{chr(10).join(other) if other else 'No other strategy context is available.'}
</Context From Other Strategies For Cross-Learning, Synthesis, Gap Anticipation, Critique Anticipation, And Orthogonality>
{REPOSITORY_CURRENT_CONTEXT_MARKER}
<Relevant Context For Your Current Strategy>
This is all the relevant context related to your current strategy. Treat this as your primary identity, branch memory, and correction anchor.
{SECTION_SEPARATOR}
{current_block}
</Relevant Context For Your Current Strategy>"""


def split_repository_context(repository: str) -> dict[str, str]:
    other, marker, current = repository.partition(REPOSITORY_CURRENT_CONTEXT_MARKER)
    return {
        "other_context": other.strip() or "No cross-strategy context is available.",
        "current_context": current.strip() if marker else repository.strip() or "No current-strategy context is available.",
    }


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
    memory_block = (
        f"<MemoryBank For Strategy {current['id']}>\n{current.get('memory_bank')}\n</MemoryBank For Strategy {current['id']}>"
        if current.get("memory_bank")
        else ""
    )
    branch_history_status = "" if current.get("history") else "<BranchHistory>Status: this branch has no completed correction history yet.</BranchHistory>"
    current_block = f"""<Strategy-{current['id']} branchVersion="{current.get('branch_version', 1)}" assigned="true">
<StrategyText>{current['main_strategy_text']}</StrategyText>
{memory_block}
<LatestCorrectionOrExecution>{current.get('latest_solution', '')}</LatestCorrectionOrExecution>
<LatestCritique>{current.get('latest_critique', '')}</LatestCritique>
<PoolHistory last="5">
{format_pool_history(current.get('pool_history', [])[-5:])}
</PoolHistory>
{branch_history_status}
</Strategy-{current['id']}>"""
    return f"""Core Challenge:
{challenge}

<Assigned Strategy Text>
{current['main_strategy_text']}
</Assigned Strategy Text>

<EvolvingDepthFirstSearchSolutionPoolContext>
Global iteration: {global_iteration}
Assigned strategy: {current['id']}
Assigned branch version: {current.get('branch_version', 1)}
Current branch-local iteration: {current.get('branch_iteration_count', 1)}
</EvolvingDepthFirstSearchSolutionPoolContext>

<Solution Pool Request>
Generate the solution pool for the assigned strategy. Use only the assigned strategy's latest correction/execution, latest critique, memory bank if present, and last solution pool outputs for the assigned strategy. Other strategies are represented only by their latest full pool outputs.
</Solution Pool Request>

<Context From Other Strategies For Cross-Learning, Synthesis, Gap Anticipation, Critique Anticipation, And Orthogonality>
{chr(10).join(other) if other else 'No other strategy solution-pool context is available.'}
</Context From Other Strategies For Cross-Learning, Synthesis, Gap Anticipation, Critique Anticipation, And Orthogonality>

{SECTION_SEPARATOR}
<Strategy-Aware Selective Knowledge Packet>
{packet or 'Not available.'}
</Strategy-Aware Selective Knowledge Packet>

{SECTION_SEPARATOR}
<Relevant Context For Your Current Strategy>
This is all the relevant context related to your current strategy. Treat this as your primary identity, branch memory, and pool-generation anchor.
{SECTION_SEPARATOR}
{current_block}
</Relevant Context For Your Current Strategy>"""


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

Create one unified memory bank for this strategy branch. Do not summarize the prose of solutions. Summarize the exploration space:
- Validated Invariants
- Dead Ends
- Persistent Flaws
- Useful Techniques
- Refuted Assumptions
- Open Questions
- Branch-Level Guidance For Future Corrections

If a previous memory bank is provided, recursively merge it with the new raw history so no earlier lessons are lost."""


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

Return only JSON:
{{
  "analysis_summary": "short summary",
  "strategies": [
    {{
      "strategy_id": "main1",
      "decision": "keep",
      "reasoning": "evidence-based reason"
    }}
  ]
}}

Decision must be exactly "keep" or "update". Mark update only when the branch's strategy should be replaced by a new branch, not when ordinary correction can fix execution errors."""


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

Generate exactly one replacement strategy for every strategy marked "update". Keep the same strategy_id slot, but the text must be a genuinely new branch that avoids the failed strategy's conceptual trap.

Return only JSON:
{{
  "strategies": [
    {{
      "strategy_id": "main1",
      "strategy": "Replacement strategy text"
    }}
  ]
}}"""


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
        f"Strategies recently updated and needing fresh targeted hypotheses: {', '.join(updated_strategy_ids)}. Flush old slot-specific assumptions for these strategies."
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

Return only JSON:
{{
  "hypotheses": [
    {{
      "text": "Hypothesis text",
      "target_strategies": ["main1"]
    }}
  ]
}}

Use empty target_strategies only for globally useful hypotheses. Do not solve the original challenge or embed assumed final answers."""
