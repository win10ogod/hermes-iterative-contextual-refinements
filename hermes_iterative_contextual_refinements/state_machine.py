"""Upstream-shaped ICR state machine artifacts.

The source application stores React mode state and LangGraph state through
ModeStateHandler plus VersionedState exports. Hermes run records are already
durable JSON artifacts, so this module projects each completed run into that
upstream state shape and adds direct indexes for agent-side replay/audit.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from .json_utils import utc_now_iso
from .source_prompts import SOURCE_PROMPT_SHA256


SCHEMA_VERSION = "icr.hermes.state_machine.v1"
UPSTREAM_STATE_VERSION = 1

MODE_TO_UPSTREAM = {
    "deepthink": "deepthink",
    "evolving_deepthink": "deepthink",
    "adaptive_deepthink": "adaptive-deepthink",
    "contextual_refinement": "contextual",
    "agentic_refinement": "agentic",
    "dca": "dynamic-compute",
}


def attach_state_machine(record: dict[str, Any]) -> dict[str, Any]:
    """Attach a complete state-machine projection to a run record."""

    record.setdefault("artifacts", {})["state_machine"] = build_state_machine(record)
    record["updated_at"] = utc_now_iso()
    return record


def build_state_machine(record: dict[str, Any]) -> dict[str, Any]:
    mode = str(record.get("mode") or "")
    upstream_mode = MODE_TO_UPSTREAM.get(mode, "deepthink")
    mode_state = _mode_state(record, upstream_mode)
    graph = _graph_for(record, upstream_mode)
    transition_log = _transition_log(record, graph)
    indexes = _indexes(record, transition_log)
    exported_config = _exported_config(record, upstream_mode, mode_state)
    versioned_state = {
        "_version": UPSTREAM_STATE_VERSION,
        "_exportedAt": record.get("updated_at") or utc_now_iso(),
        "_mode": upstream_mode,
        "_appVersion": "hermes-iterative-contextual-refinements/0.1.0",
        "data": {
            "currentMode": upstream_mode,
            "initialIdea": _initial_idea(record),
            "selectedModel": _selected_model(record),
            "modeState": mode_state,
            "embeddedStates": _embedded_states(record, upstream_mode),
            "customPrompts": _custom_prompt_state(),
            "modelParameters": _model_parameters(record.get("config") or {}, mode),
            "solutionPoolVersions": _solution_pool_versions(record),
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "upstream_state_version": UPSTREAM_STATE_VERSION,
        "source": {
            "project": "Iterative-Contextual-Refinements",
            "state_files": [
                "Core/State.ts",
                "Core/Types.ts",
                "Core/StateSerializer/ModeStateHandler.ts",
                "Core/StateSerializer/StateVersion.ts",
                "Agentic/AgenticToolGraph.ts",
                "AdaptiveDeepthink/AdaptiveDeepthinkToolGraph.ts",
                "Deepthink/DeepthinkCore.ts",
                "Contextual/ContextualCore.ts",
                "Deepthink/DCA/DCACore.ts",
            ],
        },
        "mode": mode,
        "upstream_mode": upstream_mode,
        "status": record.get("status"),
        "global_state": _global_state(record, upstream_mode),
        "exported_config": exported_config,
        "versioned_state": versioned_state,
        "mode_state_handler": _mode_state_handler(upstream_mode),
        "mode_state": mode_state,
        "graph": graph,
        "transition_log": transition_log,
        "indexes": indexes,
        "restore_plan": _restore_plan(upstream_mode),
        "serialization": {
            "native_format": "json",
            "upstream_formats_mirrored": ["json", "msgpack", "gzip"],
            "hermes_storage": "$HERMES_HOME/icr/runs/<run_id>.json",
            "note": "Hermes persists full JSON records; this artifact carries the VersionedState-compatible payload for import/replay tooling.",
        },
        "parity_notes": _parity_notes(record, upstream_mode),
    }


def _mode_state(record: dict[str, Any], upstream_mode: str) -> dict[str, Any] | None:
    if upstream_mode == "deepthink":
        return _deepthink_export_state(record)
    if upstream_mode == "agentic":
        return _agentic_state(record)
    if upstream_mode == "contextual":
        return _contextual_state(record)
    if upstream_mode == "adaptive-deepthink":
        return _adaptive_store_state(record)
    if upstream_mode == "dynamic-compute":
        return _dca_state(record)
    return None


def _deepthink_export_state(record: dict[str, Any]) -> dict[str, Any]:
    pipeline = _deepthink_pipeline(record)
    return {
        "pipeline": pipeline,
        "solutionPoolVersions": _solution_pool_versions(record),
        "activeTabId": pipeline["activeTabId"],
    }


def _deepthink_pipeline(record: dict[str, Any]) -> dict[str, Any]:
    artifacts = record.get("artifacts") or {}
    mode = str(record.get("mode") or "")
    challenge = _initial_idea(record)
    final = artifacts.get("final") or {}
    calls = record.get("llm_calls") or []
    evolving = mode == "evolving_deepthink"
    strategies = _evolving_strategies(record) if evolving else _single_pass_strategies(record)
    hypotheses = _deepthink_hypotheses(record)
    hypothesis_rounds = _deepthink_hypothesis_rounds(record)
    status = "completed" if record.get("status") == "completed" else "error" if record.get("status") == "error" else "processing"
    pipeline = {
        "id": f"deepthink-{record.get('run_id', 'run')}",
        "challenge": challenge,
        "challengeText": challenge,
        "challengeImageBase64": None,
        "challengeImageMimeType": None,
        "status": status,
        "error": _first_error(record),
        "activeTabId": "strategic-solver",
        "activeStrategyTab": 0,
        "isStopRequested": False,
        "retryAttempt": None,
        "requestPromptInitialStrategyGen": _first_prompt(calls, "deepthink.initial_strategy_generation"),
        "initialStrategies": strategies,
        "requestPromptHypothesisGen": _first_prompt(calls, "deepthink.hypothesis_generation"),
        "hypotheses": hypotheses,
        "hypothesisHistory": [hypotheses] if hypotheses else [],
        "hypothesisRounds": hypothesis_rounds,
        "hypothesisGenStatus": "completed" if hypotheses or (record.get("config") or {}).get("hypotheses") == 0 else "pending",
        "hypothesisGenError": None,
        "hypothesisGenRetryAttempt": None,
        "knowledgePacket": artifacts.get("knowledge_packet") or _latest_round_field(hypothesis_rounds, "packet") or "",
        "solutionCritiques": _solution_critique_agents(record),
        "solutionCritiquesStatus": "completed" if artifacts.get("branches") or artifacts.get("active_branches") else "pending",
        "solutionCritiquesError": None,
        "dissectedObservationsSynthesis": _synthesis_text(record),
        "dissectedSynthesisRequestPrompt": _first_prompt(calls, "deepthink.dissected_observations_synthesis"),
        "dissectedSynthesisStatus": "completed" if _synthesis_text(record) else "pending",
        "dissectedSynthesisError": None,
        "postQualityFilterAgents": _post_quality_filter_agents(record),
        "postQualityFilterStatus": "completed" if artifacts.get("pqf_decisions") else "pending",
        "postQualityFilterError": None,
        "postQualityFilterIterationCount": len(artifacts.get("pqf_decisions") or []),
        "memoryBankAgents": _memory_bank_agents(record),
        "strategicSolverComplete": record.get("status") == "completed",
        "hypothesisExplorerComplete": record.get("status") == "completed",
        "finalJudgedBestStrategyId": _best_candidate_id(final),
        "finalJudgedBestSolution": final.get("judge_response") if isinstance(final, dict) else None,
        "finalJudgingRequestPrompt": final.get("final_judge_input") if isinstance(final, dict) else None,
        "finalJudgingResponseText": final.get("judge_response") if isinstance(final, dict) else None,
        "finalJudgingStatus": "completed" if isinstance(final, dict) and final.get("judge_response") else "pending",
        "finalJudgingError": None,
        "finalJudgingRetryAttempt": None,
        "finalJudgingStatusDescription": "Final judge completed." if isinstance(final, dict) and final.get("judge_response") else "",
        "structuredSolutionPoolEnabled": bool(artifacts.get("structured_solution_pool_agents")),
        "structuredSolutionPool": _structured_solution_pool_text(record),
        "structuredSolutionPoolAgents": _structured_solution_pool_agents(record),
        "structuredSolutionPoolStatus": "completed" if artifacts.get("structured_solution_pool_agents") else "pending",
        "structuredSolutionPoolError": None,
        "hypothesisInjectionMode": (record.get("config") or {}).get("hypothesis_injection_mode"),
        "strategySpecificKnowledgePackets": artifacts.get("strategy_specific_packets") or _latest_round_field(hypothesis_rounds, "strategyPackets") or {},
        "liveEvents": _live_events(record),
        "deepthinkVariant": "evolving_dfs" if evolving else "single_pass",
    }
    return pipeline


def _single_pass_strategies(record: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = record.get("artifacts") or {}
    calls = record.get("llm_calls") or []
    branches = artifacts.get("branches") or []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for branch in branches:
        grouped[str(branch.get("main_strategy_id"))].append(branch)
    result = []
    for strategy in artifacts.get("strategies") or []:
        sid = str(strategy.get("id"))
        strategy_branches = grouped.get(sid, [])
        sub_strategies = [_single_pass_sub_strategy(branch, calls) for branch in strategy_branches]
        result.append(
            {
                "id": sid,
                "strategyText": strategy.get("text", ""),
                "requestPromptSubStrategyGen": _find_prompt(calls, "deepthink.sub_strategy_generation", strategy.get("text", "")),
                "subStrategies": sub_strategies,
                "status": "completed",
                "error": None,
                "isDetailsOpen": False,
                "retryAttempt": None,
                "strategyFormat": "markdown",
                "generatedByPostQualityFilter": False,
                "updatedByPostQualityFilter": False,
                "branchVersion": strategy.get("branch_version", 1),
                "branchIterationCount": 1 if sub_strategies else 0,
                "memoryBank": None,
                "replacementHistory": [],
                "judgedBestSubStrategyId": _best_candidate_id(artifacts.get("final") or {}),
                "judgedBestSolution": (artifacts.get("final") or {}).get("judge_response"),
                "judgingRequestPrompt": (artifacts.get("final") or {}).get("final_judge_input"),
                "judgingResponseText": (artifacts.get("final") or {}).get("judge_response"),
                "judgingStatus": "completed" if (artifacts.get("final") or {}).get("judge_response") else "pending",
            }
        )
    return result


def _single_pass_sub_strategy(branch: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    branch_id = str(branch.get("id"))
    sub_text = str(branch.get("sub_strategy_text") or branch.get("main_strategy_text") or "")
    return {
        "id": branch_id,
        "subStrategyText": sub_text,
        "requestPromptSolutionAttempt": _find_prompt(calls, "deepthink.solution_attempt", sub_text),
        "solutionAttempt": branch.get("solution"),
        "solutionAttemptDisplay": branch.get("solution"),
        "solutionAttemptFinal": branch.get("solution"),
        "requestPromptSolutionCritique": _find_prompt(calls, "deepthink.solution_critique", sub_text),
        "solutionCritique": branch.get("critique"),
        "solutionCritiqueDisplay": branch.get("critique"),
        "solutionCritiqueFinal": branch.get("critique"),
        "solutionCritiqueStatus": "completed" if branch.get("critique") else "pending",
        "solutionCritiqueError": None,
        "requestPromptSelfImprovement": _find_prompt(calls, "deepthink.self_improvement", sub_text),
        "refinedSolution": branch.get("corrected_solution") or branch.get("solution"),
        "refinedSolutionDisplay": branch.get("corrected_solution") or branch.get("solution"),
        "refinedSolutionFinal": branch.get("corrected_solution") or branch.get("solution"),
        "selfImprovementStatus": "completed" if branch.get("corrected_solution") else "pending",
        "selfImprovementError": None,
        "status": "completed" if branch.get("solution") else "pending",
        "error": None,
        "isDetailsOpen": False,
        "retryAttempt": None,
        "subStrategyFormat": "markdown",
        "branchIterationCount": 1,
        "evolvingDfs": {"enabled": False, "iterations": [], "status": "idle"},
    }


def _evolving_strategies(record: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = record.get("artifacts") or {}
    calls = record.get("llm_calls") or []
    result = []
    for branch in artifacts.get("active_branches") or []:
        branch_id = str(branch.get("id"))
        sub = _evolving_sub_strategy(branch, calls)
        result.append(
            {
                "id": branch_id,
                "strategyText": branch.get("main_strategy_text", ""),
                "requestPromptSubStrategyGen": None,
                "subStrategies": [sub],
                "status": "completed" if branch.get("latest_solution") else "pending",
                "error": None,
                "isDetailsOpen": False,
                "retryAttempt": None,
                "strategyFormat": "markdown",
                "generatedByPostQualityFilter": False,
                "updatedByPostQualityFilter": bool(branch.get("replacement_history")),
                "postQualityFilterIteration": branch.get("last_hypothesis_flush_global_iteration"),
                "branchVersion": branch.get("branch_version", 1),
                "branchIterationCount": branch.get("branch_iteration_count", 0),
                "memoryBank": branch.get("memory_bank"),
                "replacementHistory": [_camel_dict(item) for item in branch.get("replacement_history") or []],
                "judgedBestSubStrategyId": sub["id"],
                "judgedBestSolution": branch.get("latest_solution"),
                "judgingStatus": "completed" if branch.get("latest_solution") else "pending",
            }
        )
    return result


def _evolving_sub_strategy(branch: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    branch_id = str(branch.get("id"))
    history = branch.get("history") or []
    iterations = []
    for idx, entry in enumerate(history, 1):
        iterations.append(
            {
                "iterationNumber": idx,
                "globalIteration": entry.get("global_iteration"),
                "branchIteration": entry.get("branch_iteration"),
                "branchVersion": entry.get("branch_version"),
                "critique": entry.get("critique", ""),
                "critiqueDisplay": entry.get("critique", ""),
                "critiqueFinal": entry.get("critique", ""),
                "correctedSolution": entry.get("solution", ""),
                "correctedSolutionDisplay": entry.get("solution", ""),
                "correctedSolutionFinal": entry.get("solution", ""),
                "timestamp": _ts_ms(entry.get("timestamp")),
                "label": entry.get("label"),
            }
        )
    return {
        "id": branch_id,
        "subStrategyText": branch.get("sub_strategy_text") or branch.get("main_strategy_text") or "",
        "requestPromptSolutionAttempt": _find_prompt(calls, "evolving_dfs.solution_attempt", branch.get("main_strategy_text", "")),
        "solutionAttempt": _first_history_solution(history),
        "solutionAttemptDisplay": _first_history_solution(history),
        "solutionAttemptFinal": _first_history_solution(history),
        "requestPromptSolutionCritique": _find_prompt(calls, "evolving_dfs.initial_solution_critique", branch.get("main_strategy_text", "")),
        "solutionCritique": _first_history_critique(history),
        "solutionCritiqueDisplay": _first_history_critique(history),
        "solutionCritiqueFinal": _first_history_critique(history),
        "solutionCritiqueStatus": "completed" if _first_history_critique(history) else "pending",
        "requestPromptSelfImprovement": _find_prompt(calls, "evolving_dfs.solution_correction", branch.get("main_strategy_text", "")),
        "refinedSolution": branch.get("latest_solution"),
        "refinedSolutionDisplay": branch.get("latest_solution"),
        "refinedSolutionFinal": branch.get("latest_solution"),
        "selfImprovementStatus": "completed" if branch.get("latest_solution") else "pending",
        "status": "completed" if branch.get("latest_solution") else "pending",
        "error": None,
        "isDetailsOpen": False,
        "retryAttempt": None,
        "subStrategyFormat": "markdown",
        "branchIterationCount": branch.get("branch_iteration_count", len(history)),
        "evolvingDfs": {
            "enabled": True,
            "iterations": iterations,
            "status": "completed" if branch.get("latest_solution") else "idle",
            "error": None,
        },
    }


def _deepthink_hypotheses(record: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = record.get("artifacts") or {}
    if "hypotheses" in artifacts:
        raw_hypotheses = artifacts.get("hypotheses") or []
        tests = artifacts.get("hypothesis_tests") or {}
    else:
        raw_hypotheses = []
        tests = {}
        for round_ in artifacts.get("hypothesis_rounds") or []:
            raw_hypotheses.extend(round_.get("hypotheses") or [])
            tests.update(round_.get("tests") or {})
    calls = record.get("llm_calls") or []
    result = []
    for item in raw_hypotheses:
        hid = str(item.get("id"))
        result.append(
            {
                "id": hid,
                "hypothesisText": item.get("text", ""),
                "testerRequestPrompt": _find_prompt(calls, "deepthink.hypothesis_testing", item.get("text", "")),
                "testerAttempt": tests.get(hid),
                "testerAttemptDisplay": tests.get(hid),
                "testerAttemptFinal": tests.get(hid),
                "testerStatus": "completed" if hid in tests else "pending",
                "testerError": None,
                "isDetailsOpen": False,
                "targetStrategyIds": item.get("target_strategy_ids", []),
                "roundNumber": item.get("round_number"),
                "globalIteration": item.get("global_iteration"),
            }
        )
    return result


def _deepthink_hypothesis_rounds(record: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = record.get("artifacts") or {}
    if artifacts.get("hypothesis_rounds"):
        return [_camel_dict(round_) for round_ in artifacts.get("hypothesis_rounds") or []]
    if artifacts.get("hypotheses") is not None:
        return [
            {
                "roundNumber": 1,
                "globalIteration": 0,
                "hypotheses": _deepthink_hypotheses(record),
                "tests": artifacts.get("hypothesis_tests") or {},
                "packet": artifacts.get("knowledge_packet") or "",
                "strategyPackets": artifacts.get("strategy_specific_packets") or {},
            }
        ]
    return []


def _solution_critique_agents(record: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = record.get("artifacts") or {}
    agents = []
    for branch in artifacts.get("branches") or []:
        if not branch.get("critique"):
            continue
        agents.append(
            {
                "id": f"critique-{branch.get('id')}",
                "subStrategyId": branch.get("id"),
                "mainStrategyId": branch.get("main_strategy_id"),
                "branchVersion": branch.get("branch_version", 1),
                "strategyTextSnapshot": branch.get("main_strategy_text"),
                "requestPrompt": _find_prompt(record.get("llm_calls") or [], "deepthink.solution_critique", branch.get("sub_strategy_text", "")),
                "critiqueResponse": branch.get("critique"),
                "critiqueResponseDisplay": branch.get("critique"),
                "critiqueResponseFinal": branch.get("critique"),
                "status": "completed",
                "error": None,
                "retryAttempt": None,
                "isDetailsOpen": False,
            }
        )
    for branch in artifacts.get("active_branches") or []:
        if not branch.get("latest_critique"):
            continue
        agents.append(
            {
                "id": f"critique-{branch.get('id')}-g{branch.get('global_iteration')}",
                "subStrategyId": branch.get("id"),
                "mainStrategyId": branch.get("id"),
                "branchVersion": branch.get("branch_version", 1),
                "strategyTextSnapshot": branch.get("main_strategy_text"),
                "critiqueResponse": branch.get("latest_critique"),
                "critiqueResponseDisplay": branch.get("latest_critique"),
                "critiqueResponseFinal": branch.get("latest_critique"),
                "status": "completed",
                "globalIteration": branch.get("global_iteration"),
                "branchIteration": branch.get("branch_iteration_count"),
                "error": None,
                "isDetailsOpen": False,
            }
        )
    return agents


def _post_quality_filter_agents(record: dict[str, Any]) -> list[dict[str, Any]]:
    agents = []
    for idx, decision in enumerate((record.get("artifacts") or {}).get("pqf_decisions") or [], 1):
        sid = str(decision.get("strategy_id") or "")
        keep = decision.get("decision") == "keep"
        agents.append(
            {
                "id": f"pqf-{idx}",
                "iterationNumber": idx,
                "requestPrompt": None,
                "evaluationResponse": decision.get("reasoning", ""),
                "prunedStrategyIds": [] if keep else [sid],
                "continuedStrategyIds": [sid] if keep else [],
                "reasoning": decision.get("reasoning", ""),
                "rawResponse": decision,
                "status": "completed",
                "error": None,
                "isDetailsOpen": False,
                "retryAttempt": None,
                "groupIndex": (idx - 1) // 2,
                "groupStrategyIds": [sid],
            }
        )
    return agents


def _memory_bank_agents(record: dict[str, Any]) -> list[dict[str, Any]]:
    agents = []
    for idx, item in enumerate((record.get("artifacts") or {}).get("memory_bank_agents") or [], 1):
        agents.append(
            {
                "id": f"memory-{idx}-{item.get('main_strategy_id')}",
                "mainStrategyId": item.get("main_strategy_id"),
                "branchVersion": item.get("branch_version"),
                "requestPrompt": None,
                "memoryBank": item.get("memory_bank"),
                "status": "completed" if item.get("memory_bank") else "pending",
                "error": None,
                "retryAttempt": None,
                "globalIteration": item.get("global_iteration"),
                "branchIterationStart": item.get("branch_iteration_start"),
                "branchIterationEnd": item.get("branch_iteration_end"),
            }
        )
    return agents


def _structured_solution_pool_agents(record: dict[str, Any]) -> list[dict[str, Any]]:
    agents = []
    for idx, item in enumerate((record.get("artifacts") or {}).get("structured_solution_pool_agents") or [], 1):
        agents.append(
            {
                "id": f"pool-{idx}-{item.get('main_strategy_id')}",
                "mainStrategyId": item.get("main_strategy_id"),
                "branchVersion": item.get("branch_version"),
                "requestPrompt": None,
                "poolResponse": item.get("pool_response"),
                "parsedPoolResponse": item.get("parsed_pool_response"),
                "status": "completed" if item.get("parsed_pool_response") else "pending",
                "error": None,
                "retryAttempt": None,
                "isDetailsOpen": False,
                "globalIteration": item.get("global_iteration"),
                "branchIteration": item.get("branch_iteration"),
            }
        )
    return agents


def _contextual_state(record: dict[str, Any]) -> dict[str, Any] | None:
    state = (record.get("artifacts") or {}).get("contextual_state")
    if not state:
        return None
    result = _camel_dict(state)
    result.setdefault("id", f"contextual-{record.get('run_id', 'run')}")
    result["isProcessing"] = record.get("status") == "processing"
    result["isRunning"] = record.get("status") == "processing"
    result["messages"] = [
        {
            "id": f"contextual-msg-{idx}",
            "role": msg.get("role"),
            "content": msg.get("content", ""),
            "timestamp": _ts_ms(msg.get("timestamp")),
            "iterationNumber": msg.get("iteration_number") or msg.get("iterationNumber") or 0,
            "status": msg.get("status") or "success",
            "blocks": msg.get("blocks", []),
            "codeExecution": msg.get("code_execution") or msg.get("codeExecution") or [],
        }
        for idx, msg in enumerate(state.get("messages") or [], 1)
    ]
    result["contentHistory"] = [_history_entry(item) for item in state.get("content_history") or []]
    result["memorySnapshots"] = [_camel_dict(item) for item in state.get("memory_snapshots") or []]
    return result


def _agentic_state(record: dict[str, Any]) -> dict[str, Any] | None:
    state = (record.get("artifacts") or {}).get("agentic_state")
    if not state:
        return None
    messages = _agentic_messages(state)
    return {
        "id": f"agentic-{record.get('run_id', 'run')}",
        "originalContent": state.get("original_content", ""),
        "currentContent": state.get("current_content", ""),
        "messages": messages,
        "isProcessing": record.get("status") == "processing",
        "isComplete": bool(state.get("is_complete")),
        "error": _first_error(record),
        "contentHistory": [_history_entry(item) for item in state.get("content_history") or []],
        "graphState": {
            "messages": messages,
            "currentContent": state.get("current_content", ""),
            "contentHistory": [_history_entry(item) for item in state.get("content_history") or []],
            "verifierReports": list(state.get("verifier_reports") or []),
            "verificationCount": state.get("verification_count", 0),
            "lastVerifiedContent": state.get("last_verified_content"),
            "shouldExit": bool(state.get("is_complete")),
        },
    }


def _agentic_messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    tool_events = list(state.get("tool_events") or [])
    system_tool_index = 0
    messages = []
    for idx, msg in enumerate(state.get("messages") or [], 1):
        item = {
            "id": f"agentic-msg-{idx}",
            "role": msg.get("role"),
            "content": msg.get("content", ""),
            "timestamp": _ts_ms(msg.get("timestamp")),
            "status": msg.get("status") or "success",
        }
        if msg.get("role") == "agent":
            item["segments"] = [{"kind": "text", "text": msg.get("content", "")}]
        if msg.get("role") == "system" and system_tool_index < len(tool_events):
            event = tool_events[system_tool_index]
            system_tool_index += 1
            item["blocks"] = [
                {
                    "kind": "error" if (event.get("result") or {}).get("status") == "error" else "tool_result",
                    "tool": event.get("tool"),
                    "result": (event.get("result") or {}).get("content", ""),
                    "toolCall": _agentic_tool_call(event.get("tool"), event.get("arguments") or {}),
                }
            ]
        messages.append(item)
    return messages


def _agentic_tool_call(name: str | None, args: dict[str, Any]) -> dict[str, Any]:
    if name == "multi_edit":
        operations = []
        for op in args.get("operations") or []:
            operation = {"type": op.get("action"), "params": [op.get("target")]}
            if op.get("content") is not None:
                operation["params"].append(op.get("content"))
            operations.append(operation)
        return {"type": "multi_edit", "operations": operations}
    if name == "read_current_content" and "startLine" in args and "endLine" in args:
        return {"type": "read_current_content", "params": [args["startLine"], args["endLine"]]}
    if name == "searchacademia":
        return {"type": "searchacademia", "query": args.get("query", "")}
    if name == "searchacademia_and":
        return {"type": "searchacademia_and", "terms": args.get("terms", [])}
    return {"type": name or "tool"}


def _adaptive_store_state(record: dict[str, Any]) -> dict[str, Any] | None:
    state = (record.get("artifacts") or {}).get("adaptive_state")
    if not state:
        return None
    core = _adaptive_core_state(record, state)
    messages = _adaptive_messages(record, state)
    return {
        "id": f"adaptive-{record.get('run_id', 'run')}",
        "coreState": core,
        "messages": messages,
        "isProcessing": record.get("status") == "processing",
        "isComplete": bool(state.get("selected_solution")),
        "error": _first_error(record),
        "deepthinkPipelineState": _adaptive_deepthink_pipeline(record, state),
        "navigationState": {"currentTab": "strategic-solver"},
        "graphState": {
            "messages": messages,
            "coreState": core,
            "shouldExit": bool(state.get("selected_solution")),
        },
    }


def _adaptive_core_state(record: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"adaptive-core-{record.get('run_id', 'run')}",
        "question": _initial_idea(record),
        "status": "completed" if state.get("selected_solution") else "processing",
        "error": None,
        "strategies": _map_state(state.get("strategies") or {}),
        "hypotheses": _map_state(state.get("hypotheses") or {}),
        "hypothesisTestings": _map_state(state.get("hypothesis_testings") or {}),
        "executions": _map_state(state.get("executions") or {}),
        "critiques": _map_state(state.get("critiques") or {}),
        "correctedSolutions": _map_state(state.get("corrected_solutions") or {}),
        "selectedSolution": state.get("selected_solution"),
    }


def _adaptive_messages(record: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "id": "adaptive-user-1",
            "role": "user",
            "content": f"Started Adaptive Deepthink run: {_initial_idea(record)}",
            "timestamp": _ts_ms(record.get("created_at")),
            "status": "success",
        }
    ]
    event_iter = iter(state.get("tool_events") or [])
    idx = 1
    for call in record.get("llm_calls") or []:
        if call.get("purpose") != "adaptive_deepthink.orchestrator":
            continue
        parsed = call.get("parsed_data") or {}
        tool_calls = parsed.get("tool_calls") or []
        segments = []
        text = str(parsed.get("assistant_text") or "")
        if text:
            segments.append({"kind": "text", "text": text})
        for tool_call in tool_calls:
            segments.append({"kind": "tool", "tool": {"type": tool_call.get("name"), **(tool_call.get("arguments") or {})}})
        idx += 1
        messages.append(
            {
                "id": f"adaptive-agent-{idx}",
                "role": "agent",
                "content": text,
                "timestamp": _ts_ms(call.get("completed_at") or call.get("created_at")),
                "status": "success" if call.get("status") == "completed" else "error",
                "segments": segments,
            }
        )
        for _tool_call in tool_calls:
            event = next(event_iter, None)
            if not event:
                continue
            idx += 1
            result = str(event.get("result") or "")
            is_error = result.startswith("[ERROR:")
            messages.append(
                {
                    "id": f"adaptive-system-{idx}",
                    "role": "system",
                    "content": result,
                    "timestamp": _ts_ms(call.get("completed_at") or call.get("created_at")),
                    "status": "error" if is_error else "success",
                    "blocks": [
                        {
                            "kind": "error" if is_error else "tool_result",
                            "tool": event.get("tool"),
                            "result": result,
                        }
                    ],
                }
            )
    return messages


def _adaptive_deepthink_pipeline(record: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    pipeline = {
        "id": f"deepthink-embedded-{record.get('run_id', 'run')}",
        "challenge": _initial_idea(record),
        "challengeText": "",
        "status": "completed" if state.get("selected_solution") else "processing",
        "activeTabId": "strategic-solver",
        "activeStrategyTab": 0,
        "initialStrategies": [],
        "hypotheses": [],
        "solutionCritiques": [],
        "postQualityFilterAgents": [],
        "structuredSolutionPoolAgents": [],
        "strategicSolverComplete": bool(state.get("selected_solution")),
        "hypothesisExplorerComplete": bool(state.get("hypotheses")),
        "knowledgePacket": "",
        "finalJudgedBestSolution": state.get("selected_solution"),
        "finalJudgingResponseText": state.get("selected_solution"),
        "finalJudgingStatus": "completed" if state.get("selected_solution") else "pending",
        "isStopRequested": False,
        "hypothesisGenStatus": "completed" if state.get("hypotheses") else "pending",
        "dissectedSynthesisStatus": "pending",
        "solutionCritiquesStatus": "completed" if state.get("critiques") else "pending",
    }
    for sid, data in (state.get("strategies") or {}).items():
        execution = (state.get("executions") or {}).get(f"execution-{sid}", {})
        corrected = (state.get("corrected_solutions") or {}).get(f"execution-{sid}:Corrected", {})
        pipeline["initialStrategies"].append(
            {
                "id": sid,
                "strategyText": data.get("text", ""),
                "subStrategies": [
                    {
                        "id": sid,
                        "subStrategyText": data.get("text", ""),
                        "solutionAttempt": execution.get("execution"),
                        "refinedSolution": corrected.get("correctedSolution"),
                        "status": "completed" if execution else "pending",
                    }
                ],
                "status": "completed",
                "isDetailsOpen": False,
                "strategyFormat": "markdown",
            }
        )
    for hid, data in (state.get("hypotheses") or {}).items():
        test = (state.get("hypothesis_testings") or {}).get(hid, {})
        pipeline["hypotheses"].append(
            {
                "id": hid,
                "hypothesisText": data.get("text", ""),
                "testerAttempt": test.get("testing"),
                "testerStatus": "completed" if test else "pending",
            }
        )
    for eid, data in (state.get("critiques") or {}).items():
        pipeline["solutionCritiques"].append(
            {
                "id": f"critique-{eid}",
                "subStrategyId": eid,
                "mainStrategyId": eid,
                "critiqueResponse": data.get("critique"),
                "status": "completed",
            }
        )
    return pipeline


def _dca_state(record: dict[str, Any]) -> dict[str, Any] | None:
    state = (record.get("artifacts") or {}).get("dca_state")
    if not state:
        return None
    return {
        "id": state.get("id") or f"dca-{record.get('run_id', 'run')}",
        "problem": state.get("problem", ""),
        "status": "completed" if record.get("status") == "completed" else state.get("status", "processing"),
        "error": state.get("error") or _first_error(record),
        "solutions": [_camel_dict(solution) for solution in state.get("solutions") or []],
        "isStopRequested": bool(state.get("is_stop_requested") or state.get("isStopRequested") or False),
        "graph": {
            "rootId": "root",
            "nodes": [_camel_dict(solution) for solution in state.get("solutions") or []],
            "edges": [
                {"from": solution.get("parentId") or solution.get("parent_id"), "to": solution.get("id")}
                for solution in (_camel_dict(item) for item in state.get("solutions") or [])
                if solution.get("parentId") or solution.get("parent_id")
            ],
        },
    }


def _exported_config(record: dict[str, Any], upstream_mode: str, mode_state: dict[str, Any] | None) -> dict[str, Any]:
    active_deepthink = mode_state.get("pipeline") if upstream_mode == "deepthink" and mode_state else None
    return {
        "currentMode": upstream_mode,
        "initialIdea": _initial_idea(record),
        "selectedModel": _selected_model(record),
        "activeDeepthinkPipeline": active_deepthink,
        "activeAgenticState": mode_state if upstream_mode == "agentic" else None,
        "activeContextualState": mode_state if upstream_mode == "contextual" else None,
        "activeAdaptiveDeepthinkState": mode_state if upstream_mode == "adaptive-deepthink" else None,
        "activeDCAState": mode_state if upstream_mode == "dynamic-compute" else None,
        "activeDeepthinkProblemTabId": "strategic-solver",
        "globalStatusText": _global_status_text(record),
        "globalStatusClass": _global_status_class(record),
        "customPromptsDeepthinkState": _custom_prompt_state()["deepthink"],
        "customPromptsAgentic": _custom_prompt_state()["agentic"],
        "customPromptsAdaptiveDeepthink": _custom_prompt_state()["adaptiveDeepthink"],
        "customPromptsContextual": _custom_prompt_state()["contextual"],
        "customPromptsDCA": _custom_prompt_state()["dca"],
        "isCustomPromptsOpen": False,
        "modelParameters": _model_parameters(record.get("config") or {}, str(record.get("mode") or "")),
        "solutionPoolVersions": _solution_pool_versions(record),
    }


def _global_state(record: dict[str, Any], upstream_mode: str) -> dict[str, Any]:
    processing = record.get("status") == "processing"
    return {
        "currentMode": upstream_mode,
        "activeDeepthinkPipeline": _deepthink_pipeline(record) if upstream_mode == "deepthink" else None,
        "isGenerating": processing,
        "currentProblemImages": [],
        "isCustomPromptsOpen": False,
        "isAgenticRunning": processing and upstream_mode == "agentic",
        "isContextualRunning": processing and upstream_mode == "contextual",
        "isAdaptiveDeepthinkRunning": processing and upstream_mode == "adaptive-deepthink",
        "isDCARunning": processing and upstream_mode == "dynamic-compute",
        "geminiCodeExecutionEnabled": bool((record.get("config") or {}).get("python_execution_enabled")),
        "thinkingLevel": "high",
        "customPromptsDeepthinkState": _custom_prompt_state()["deepthink"],
        "customPromptsAgenticState": _custom_prompt_state()["agentic"],
        "customPromptsAdaptiveDeepthinkState": _custom_prompt_state()["adaptiveDeepthink"],
        "customPromptsContextualState": _custom_prompt_state()["contextual"],
        "customPromptsDCAState": _custom_prompt_state()["dca"],
    }


def _graph_for(record: dict[str, Any], upstream_mode: str) -> dict[str, Any]:
    if upstream_mode == "agentic":
        return {
            "engine": "LangGraph",
            "annotation": {
                "messages": {"reducer": "messagesStateReducer", "default": []},
                "currentContent": {"reducer": "replace", "default": ""},
                "contentHistory": {"reducer": "replace", "default": []},
                "verifierReports": {"reducer": "replace", "default": []},
                "verificationCount": {"reducer": "replace", "default": 0},
                "lastVerifiedContent": {"reducer": "replace", "default": None},
                "shouldExit": {"reducer": "replace", "default": False},
            },
            "nodes": ["agent", "tools"],
            "edges": [
                {"from": "START", "to": "agent"},
                {"from": "agent", "condition": "last AI message has tool_calls", "true": "tools", "false": "END"},
                {"from": "tools", "condition": "state.shouldExit", "true": "END", "false": "agent"},
            ],
            "shouldExit": bool(((record.get("artifacts") or {}).get("agentic_state") or {}).get("is_complete")),
        }
    if upstream_mode == "adaptive-deepthink":
        return {
            "engine": "LangGraph",
            "annotation": {
                "messages": {"reducer": "messagesStateReducer", "default": []},
                "coreState": {"reducer": "replace", "default": "createAdaptiveDeepthinkState('')"},
                "shouldExit": {"reducer": "replace", "default": False},
            },
            "nodes": ["agent", "tools"],
            "edges": [
                {"from": "START", "to": "agent"},
                {"from": "agent", "condition": "last AI message has tool_calls", "true": "tools", "false": "END"},
                {"from": "tools", "condition": "state.shouldExit", "true": "END", "false": "agent"},
            ],
            "shouldExit": bool(((record.get("artifacts") or {}).get("adaptive_state") or {}).get("selected_solution")),
        }
    if upstream_mode == "deepthink":
        mode = record.get("mode")
        stages = [
            "initial_strategy_generation",
            "sub_strategy_generation_or_direct_branch",
            "hypothesis_generation",
            "hypothesis_testing",
            "solution_attempt",
            "solution_critique",
            "self_improvement",
            "final_judge",
        ]
        if mode == "evolving_deepthink":
            stages = [
                "initial_strategy_generation",
                "initial_hypothesis_round_global_0",
                "initial_branch_execution_global_1",
                "solution_pool",
                "evolving_correction_loop",
                "memory_bank_every_5_branch_entries",
                "post_quality_filter",
                "strategy_replacement",
                "hypothesis_heartbeat_every_2_global_iterations",
                "final_judge_active_branches",
            ]
        return {"engine": "React pipeline", "nodes": stages, "edges": _linear_edges(stages)}
    if upstream_mode == "contextual":
        stages = ["main_generator", "iterative_agent", "strategic_pool_agent", "memory_agent_if_due", "loop_or_complete"]
        return {"engine": "React loop", "nodes": stages, "edges": _linear_edges(stages)}
    if upstream_mode == "dynamic-compute":
        stages = ["pool_generator", "parallel_local_pool_agents", "complete"]
        return {"engine": "React pipeline", "nodes": stages, "edges": _linear_edges(stages)}
    return {}


def _transition_log(record: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    transitions.append(
        {
            "index": 0,
            "kind": "state_created",
            "node": "START",
            "status": "completed",
            "time": record.get("created_at"),
            "mode": record.get("mode"),
        }
    )
    for call in record.get("llm_calls") or []:
        transitions.append(
            {
                "index": len(transitions),
                "kind": "llm_call",
                "node": _node_for_call(call),
                "role": call.get("role"),
                "purpose": call.get("purpose"),
                "callId": call.get("id"),
                "callKind": call.get("kind"),
                "status": call.get("status"),
                "time": call.get("created_at"),
                "completedAt": call.get("completed_at"),
                "attemptCount": call.get("attempt_count", len(call.get("attempts") or [])),
                "provider": call.get("provider"),
                "model": call.get("model"),
            }
        )
    for event in _tool_events(record):
        transitions.append(
            {
                "index": len(transitions),
                "kind": "tool_call_result",
                "node": "tools",
                "turn": event.get("turn"),
                "tool": event.get("tool"),
                "arguments": event.get("arguments"),
                "resultStatus": _tool_result_status(event.get("result")),
                "status": "completed",
                "resultPreview": _preview(event.get("result")),
            }
        )
    for event in record.get("events") or []:
        transitions.append(
            {
                "index": len(transitions),
                "kind": "record_event",
                "node": event.get("kind"),
                "status": "completed",
                "time": event.get("time"),
                "message": event.get("message"),
                "data": event.get("data", {}),
            }
        )
    transitions.append(
        {
            "index": len(transitions),
            "kind": "state_completed" if record.get("status") == "completed" else "state_error",
            "node": "END" if record.get("status") == "completed" else "ERROR",
            "status": record.get("status"),
            "time": record.get("updated_at"),
            "graphShouldExit": graph.get("shouldExit"),
        }
    )
    return transitions


def _indexes(record: dict[str, Any], transitions: list[dict[str, Any]]) -> dict[str, Any]:
    artifacts = record.get("artifacts") or {}
    calls_by_role: dict[str, list[str]] = defaultdict(list)
    calls_by_purpose: dict[str, list[str]] = defaultdict(list)
    for call in record.get("llm_calls") or []:
        calls_by_role[str(call.get("role") or "")].append(call.get("id"))
        calls_by_purpose[str(call.get("purpose") or "")].append(call.get("id"))
    tool_calls: dict[str, list[int]] = defaultdict(list)
    for event in _tool_events(record):
        tool_calls[str(event.get("tool"))].append(int(event.get("turn") or 0))
    branch_ids = [b.get("id") for b in artifacts.get("branches") or []] + [b.get("id") for b in artifacts.get("active_branches") or []]
    strategy_ids = [s.get("id") for s in artifacts.get("strategies") or []] or [b.get("id") for b in artifacts.get("active_branches") or []]
    hypothesis_ids = [h.get("id") for h in artifacts.get("hypotheses") or []]
    for round_ in artifacts.get("hypothesis_rounds") or []:
        hypothesis_ids.extend(h.get("id") for h in round_.get("hypotheses") or [])
    state = artifacts.get("agentic_state") or artifacts.get("contextual_state") or artifacts.get("adaptive_state") or artifacts.get("dca_state") or {}
    return {
        "artifactKeys": sorted(k for k in artifacts if k != "state_machine"),
        "llmCallsByRole": dict(calls_by_role),
        "llmCallsByPurpose": dict(calls_by_purpose),
        "strategyIds": [x for x in strategy_ids if x],
        "branchIds": [x for x in branch_ids if x],
        "hypothesisIds": [x for x in hypothesis_ids if x],
        "toolCallsByTool": dict(tool_calls),
        "transitionCount": len(transitions),
        "contentVersionCount": len(state.get("content_history") or state.get("contentHistory") or []),
        "messageCount": len(state.get("messages") or []),
        "finalCandidateIds": [c.get("id") for c in (artifacts.get("final") or {}).get("candidates", [])] if isinstance(artifacts.get("final"), dict) else [],
        "solutionIds": [s.get("id") for s in (artifacts.get("dca_state") or {}).get("solutions", [])],
        "optimizedFor": ["direct role lookup", "direct purpose lookup", "branch replay", "tool replay", "final candidate audit"],
    }


def _mode_state_handler(upstream_mode: str) -> dict[str, Any]:
    handlers = {
        "deepthink": "deepthinkStateHandler",
        "agentic": "agenticStateHandler",
        "contextual": "contextualStateHandler",
        "adaptive-deepthink": "adaptiveDeepthinkStateHandler",
        "dynamic-compute": "dynamicComputeStateHandler",
    }
    return {
        "modeName": upstream_mode,
        "handler": handlers.get(upstream_mode),
        "methods": ["getFullState", "restoreState", "renderAfterImport"],
        "embeddedMethods": ["getEmbeddedState", "restoreEmbeddedState"] if upstream_mode == "deepthink" else [],
    }


def _restore_plan(upstream_mode: str) -> dict[str, Any]:
    return {
        "steps": [
            "deserialize VersionedState",
            "sanitize processing/retrying/running flags to import-safe values",
            f"select ModeStateHandler for {upstream_mode}",
            "restoreState(modeState)",
            "restore embedded state when present",
            "renderAfterImport",
        ],
        "sanitizer": {
            "statusResetMap": {
                "processing": "pending",
                "retrying": "pending",
                "running": "stopped",
                "stopping": "stopped",
                "orchestrating": "idle",
                "agentic_orchestrating": "idle",
                "processing_workers": "idle",
                "orchestrating_retrying": "idle",
            },
            "booleanResetPatterns": ["^is.*Running$", "^is.*Processing$", "^isStopRequested$", "^isGenerating$"],
            "nonSerializableFieldsRemoved": ["abortController", "tabButtonElement", "contentElement", "stopButtonElement", "uiRoot", "root", "containerElement"],
        },
    }


def _parity_notes(record: dict[str, Any], upstream_mode: str) -> list[str]:
    notes = [
        "Mode state is projected into upstream React/LangGraph field names while preserving the original Hermes artifacts.",
        "Transition indexes are a Hermes optimization over upstream browser state; they do not replace raw prompts, responses, or artifacts.",
        "Custom prompt defaults are referenced by bundled upstream resource checksums; per-call system prompts remain recorded in llm_calls.",
    ]
    if upstream_mode == "deepthink" and record.get("mode") == "evolving_deepthink":
        notes.append("Evolving DFS uses upstream global_iteration 0 for the first hypothesis round and global_iteration 1 for initial branch execution.")
    if upstream_mode in {"agentic", "adaptive-deepthink"}:
        notes.append("LangGraph node/edge/reducer metadata is mirrored for replay even though Hermes executes a deterministic Python tool loop.")
    return notes


def _custom_prompt_state() -> dict[str, Any]:
    return {
        "deepthink": {"sourcePromptChecksums": {"DeepthinkPrompts.ts": SOURCE_PROMPT_SHA256["DeepthinkPrompts.ts"]}},
        "agentic": {"sourcePromptChecksums": {"AgenticModePrompt.ts": SOURCE_PROMPT_SHA256["AgenticModePrompt.ts"]}},
        "contextual": {"sourcePromptChecksums": {"ContextualPrompts.ts": SOURCE_PROMPT_SHA256["ContextualPrompts.ts"]}},
        "adaptiveDeepthink": {"sourcePromptChecksums": {"AdaptiveDeepthinkPrompt.ts": SOURCE_PROMPT_SHA256["AdaptiveDeepthinkPrompt.ts"]}},
        "dca": {"sourcePromptChecksums": {"DCAPrompts.ts": SOURCE_PROMPT_SHA256["DCAPrompts.ts"]}},
    }


def _model_parameters(config: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "temperature": 0.7,
        "topP": 0.95,
        "strategiesCount": config.get("main_strategies", 3),
        "subStrategiesCount": config.get("sub_strategies", 0),
        "textPlaceholder": "",
        "hypothesisCount": config.get("hypotheses", 3),
        "pqfAggressiveness": config.get("pqf_aggressiveness", "balanced"),
        "refinementEnabled": config.get("refinement", True),
        "skipSubStrategies": int(config.get("sub_strategies", 0) or 0) == 0,
        "dissectedObservationsEnabled": config.get("critique_synthesis", False),
        "evolvingDfsEnabled": mode == "evolving_deepthink",
        "evolvingDfsDepth": config.get("evolving_depth", 3),
        "provideAllSolutionsToCorrectors": config.get("full_solution_context", False),
    }


def _embedded_states(record: dict[str, Any], upstream_mode: str) -> dict[str, Any]:
    if upstream_mode == "deepthink":
        return {"solutionPoolVersions": _solution_pool_versions(record)}
    return {}


def _solution_pool_versions(record: dict[str, Any]) -> list[dict[str, Any]]:
    versions = []
    for idx, item in enumerate((record.get("artifacts") or {}).get("structured_solution_pool_agents") or [], 1):
        content = item.get("pool_response")
        if not content and item.get("parsed_pool_response"):
            content = str(item.get("parsed_pool_response"))
        versions.append(
            {
                "content": content or "",
                "title": f"Solution Pool {idx}: {item.get('main_strategy_id')}",
                "timestamp": _ts_ms(item.get("timestamp") or record.get("updated_at")),
            }
        )
    return versions


def _live_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for idx, call in enumerate(record.get("llm_calls") or [], 1):
        events.append(
            {
                "id": f"live-{idx}",
                "timestamp": _ts_ms(call.get("created_at")),
                "agentName": call.get("role") or "",
                "stepDescription": call.get("purpose") or "",
                "eventType": "agent_complete" if call.get("status") == "completed" else "agent_error",
                "message": call.get("status") or "",
            }
        )
    return events


def _tool_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = record.get("artifacts") or {}
    state = artifacts.get("agentic_state") or artifacts.get("adaptive_state") or {}
    return list(state.get("tool_events") or [])


def _linear_edges(stages: list[str]) -> list[dict[str, str]]:
    if not stages:
        return []
    edges = [{"from": "START", "to": stages[0]}]
    edges.extend({"from": left, "to": right} for left, right in zip(stages, stages[1:], strict=False))
    edges.append({"from": stages[-1], "to": "END"})
    return edges


def _initial_idea(record: dict[str, Any]) -> str:
    request = record.get("request") or {}
    return str(request.get("challenge") or request.get("content") or request.get("instruction") or "")


def _selected_model(record: dict[str, Any]) -> str:
    for call in record.get("llm_calls") or []:
        if call.get("model"):
            return str(call["model"])
    return ""


def _first_error(record: dict[str, Any]) -> str | None:
    errors = record.get("errors") or []
    if not errors:
        return None
    return str(errors[0].get("message") or errors[0])


def _global_status_text(record: dict[str, Any]) -> str:
    status = record.get("status")
    if status == "completed":
        return "ICR run completed."
    if status == "error":
        return "ICR run failed."
    return "ICR run is processing."


def _global_status_class(record: dict[str, Any]) -> str:
    status = record.get("status")
    if status == "completed":
        return "success"
    if status == "error":
        return "error"
    return "processing"


def _best_candidate_id(final: dict[str, Any]) -> str | None:
    candidates = final.get("candidates") if isinstance(final, dict) else None
    if candidates:
        return candidates[0].get("id")
    return None


def _synthesis_text(record: dict[str, Any]) -> str:
    for call in record.get("llm_calls") or []:
        if call.get("purpose") == "deepthink.dissected_observations_synthesis":
            return str(call.get("raw_response") or "")
    return ""


def _structured_solution_pool_text(record: dict[str, Any]) -> str:
    parts = []
    for item in (record.get("artifacts") or {}).get("structured_solution_pool_agents") or []:
        parts.append(str(item.get("pool_response") or item.get("parsed_pool_response") or ""))
    return "\n\n".join(part for part in parts if part)


def _latest_round_field(rounds: list[dict[str, Any]], field: str) -> Any:
    if not rounds:
        return None
    return rounds[-1].get(field)


def _first_history_solution(history: list[dict[str, Any]]) -> str | None:
    return history[0].get("solution") if history else None


def _first_history_critique(history: list[dict[str, Any]]) -> str | None:
    return history[0].get("critique") if history else None


def _first_prompt(calls: list[dict[str, Any]], purpose: str) -> str | None:
    for call in calls:
        if call.get("purpose") == purpose:
            return call.get("raw_prompt")
    return None


def _find_prompt(calls: list[dict[str, Any]], purpose: str, *needles: Any) -> str | None:
    required = [str(needle) for needle in needles if str(needle or "").strip()]
    fallback = None
    for call in calls:
        if call.get("purpose") != purpose:
            continue
        prompt = str(call.get("raw_prompt") or "")
        fallback = fallback or prompt
        if all(needle in prompt for needle in required):
            return prompt
    return fallback


def _node_for_call(call: dict[str, Any]) -> str:
    purpose = str(call.get("purpose") or "")
    if "." in purpose:
        return purpose.split(".", 1)[1]
    return purpose or str(call.get("role") or "")


def _tool_result_status(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("status") or "success")
    text = str(result or "")
    return "error" if text.startswith("[ERROR:") else "success"


def _preview(value: Any, limit: int = 240) -> str:
    if isinstance(value, dict):
        text = str(value.get("content") or value)
    else:
        text = str(value or "")
    text = text.replace("\n", " ").strip()
    return text[:limit]


def _map_state(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _camel_dict(item) for key, item in value.items()}


def _history_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": item.get("content", ""),
        "title": item.get("title", ""),
        "timestamp": _ts_ms(item.get("timestamp")),
    }


def _camel_dict(value: Any) -> Any:
    if isinstance(value, list):
        return [_camel_dict(item) for item in value]
    if isinstance(value, dict):
        return {_camel_key(str(key)): _camel_dict(item) for key, item in value.items()}
    return value


def _camel_key(value: str) -> str:
    parts = value.split("_")
    if len(parts) == 1:
        return value
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _ts_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if not value:
        return 0
    text = str(value)
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return 0
