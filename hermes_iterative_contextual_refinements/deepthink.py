"""Deepthink single-pass and Evolving DFS engines."""

from __future__ import annotations

import threading
from typing import Any

from . import prompts
from .concurrency import run_parallel
from .config import ICRConfig
from .constants import HYPOTHESIS_HEARTBEAT_INTERVAL, MEMORY_INTERVAL, PQF_GROUP_SIZE
from .json_utils import dumps, utc_now_iso
from .llm import ICRLlm
from .schemas import HYPOTHESES_SCHEMA, PQF_SCHEMA, SOLUTION_POOL_SCHEMA, STRATEGIES_SCHEMA, STRATEGY_UPDATE_SCHEMA, SUB_STRATEGIES_SCHEMA


class DeepthinkEngine:
    def __init__(self, llm: ICRLlm, record: dict[str, Any], config: ICRConfig):
        self.llm = llm
        self.record = record
        self.config = config
        self._lock = threading.RLock()

    def run_single_pass(self, challenge: str) -> dict[str, Any]:
        strategies = self._generate_main_strategies(challenge, self.config.main_strategies)
        branches = self._build_branches(challenge, strategies)
        hypotheses, tests, packet, packets = self._hypothesis_round(challenge, strategies, round_number=1, global_iteration=0)

        def attempt_solution(branch: dict[str, Any]) -> str:
            packet_for_branch = packets.get(branch["main_strategy_id"], packet)
            return self.llm.complete(
                role="solution_attempt",
                purpose="deepthink.solution_attempt",
                prompt=prompts.execution_prompt(challenge, branch, strategies, packet_for_branch),
                system_prompt=prompts.system_prompt("solution_attempt"),
            )

        for branch, solution in zip(branches, run_parallel(branches, attempt_solution), strict=True):
            branch["solution"] = solution

        if self.config.refinement:
            def critique_solution(branch: dict[str, Any]) -> str:
                return self.llm.complete(
                    role="solution_critique",
                    purpose="deepthink.solution_critique",
                    prompt=prompts.critique_prompt(challenge, branch, branch["solution"]),
                    system_prompt=prompts.system_prompt("solution_critique"),
                )

            for branch, critique in zip(branches, run_parallel(branches, critique_solution), strict=True):
                branch["critique"] = critique

            synthesis = ""
            if self.config.critique_synthesis:
                synthesis_packet = packet if self.config.include_hypotheses_in_synthesis else ""
                synthesis = self.llm.complete(
                    role="dissected_synthesis",
                    purpose="deepthink.dissected_observations_synthesis",
                    prompt=prompts.synthesis_prompt(challenge, branches, synthesis_packet),
                    system_prompt=prompts.system_prompt("dissected_synthesis"),
                )

            def correct_solution(branch: dict[str, Any]) -> str:
                full_context = prompts.full_solution_context(branches, branch["id"]) if self.config.full_solution_context else ""
                return self.llm.complete(
                    role="self_improvement",
                    purpose="deepthink.self_improvement",
                    prompt=prompts.correction_prompt(
                        challenge,
                        branch,
                        branch["solution"],
                        branch.get("critique", ""),
                        synthesis=synthesis,
                        full_context=full_context,
                        packet=packets.get(branch["main_strategy_id"], packet),
                    ),
                    system_prompt=prompts.system_prompt("self_improvement"),
                )

            for branch, corrected in zip(branches, run_parallel(branches, correct_solution), strict=True):
                branch["corrected_solution"] = corrected

        candidates = [
            {
                "id": branch["id"],
                "main_strategy_id": branch["main_strategy_id"],
                "sub_strategy_text": branch["sub_strategy_text"],
                "solution": branch.get("corrected_solution") or branch["solution"],
            }
            for branch in branches
        ]
        final_prompt = prompts.final_judge_prompt(challenge, candidates)
        judge = self.llm.complete(
            role="final_judge",
            purpose="deepthink.final_judge",
            prompt=final_prompt,
            system_prompt=prompts.system_prompt("final_judge"),
        )
        result = {
            "strategies": strategies,
            "branches": branches,
            "hypotheses": hypotheses,
            "hypothesis_tests": tests,
            "knowledge_packet": packet,
            "strategy_specific_packets": packets,
            "final": {
                "judge_response": judge,
                "candidates": candidates,
                "final_judge_input": final_prompt,
            },
        }
        self.record["artifacts"].update(result)
        return result

    def run_evolving_dfs(self, challenge: str) -> dict[str, Any]:
        strategies = self._generate_main_strategies(challenge, self.config.main_strategies)
        hypotheses, tests, packet, packets = self._hypothesis_round(challenge, strategies, round_number=1, global_iteration=0, selective=True)
        hypothesis_rounds = [
            {
                "round_number": 1,
                "global_iteration": 0,
                "hypotheses": hypotheses,
                "tests": tests,
                "packet": packet,
                "strategy_packets": packets,
            }
        ]

        branches = [
            self._new_evolving_branch(strategy, index, packets.get(strategy["id"], packet))
            for index, strategy in enumerate(strategies, 1)
        ]
        run_parallel(branches, lambda branch: self._execute_and_critique_initial(challenge, branch, strategies, global_iteration=1))
        run_parallel(branches, lambda branch: self._run_solution_pool(challenge, branch, branches, global_iteration=1))

        archives: list[dict[str, Any]] = []
        updated_since_heartbeat: list[str] = []
        pqf_decisions: list[dict[str, Any]] = []
        memory_agents: list[dict[str, Any]] = []
        pool_agents: list[dict[str, Any]] = []
        pool_agents.extend(self.record["artifacts"].setdefault("structured_solution_pool_agents", []))

        for global_iteration in range(2, self.config.evolving_depth + 1):
            snapshots = [dict(branch) for branch in branches]

            def refine_branch(branch: dict[str, Any]) -> None:
                repository = prompts.correction_repository(branch, snapshots)
                branch_iteration = branch["branch_iteration_count"] + 1
                correction = self.llm.complete(
                    role="self_improvement",
                    purpose="evolving_dfs.solution_correction",
                    prompt=prompts.correction_prompt(
                        challenge,
                        branch,
                        branch["latest_solution"],
                        branch["latest_critique"],
                        repository=repository,
                        packet=branch.get("hypothesis_packet", ""),
                        global_iteration=global_iteration,
                        branch_iteration=branch_iteration,
                    ),
                    system_prompt=prompts.system_prompt("self_improvement"),
                )
                critique = self.llm.complete(
                    role="solution_critique",
                    purpose="evolving_dfs.solution_critique",
                    prompt=prompts.critique_prompt(challenge, branch, correction, branch.get("history", [])),
                    system_prompt=prompts.system_prompt("solution_critique"),
                )
                branch["branch_iteration_count"] = branch_iteration
                branch["global_iteration"] = global_iteration
                branch["latest_solution"] = correction
                branch["latest_critique"] = critique
                branch["history"].append(
                    {
                        "global_iteration": global_iteration,
                        "branch_iteration": branch_iteration,
                        "branch_version": branch["branch_version"],
                        "label": "correction",
                        "solution": correction,
                        "critique": critique,
                        "timestamp": utc_now_iso(),
                    }
                )

            run_parallel(branches, refine_branch)
            run_parallel(branches, lambda branch: self._run_solution_pool(challenge, branch, branches, global_iteration=global_iteration))

            if self.config.hypotheses > 0 and global_iteration % HYPOTHESIS_HEARTBEAT_INTERVAL == 0:
                previous = dumps(hypothesis_rounds)
                prompt = prompts.hypothesis_refresh_prompt(
                    challenge,
                    self.config.hypotheses,
                    global_iteration,
                    hypothesis_rounds,
                    branches,
                    updated_since_heartbeat,
                )
                hypotheses = self._generate_hypotheses_from_prompt(prompt, round_number=len(hypothesis_rounds) + 1, global_iteration=global_iteration)
                tests = self._test_hypotheses(challenge, hypotheses)
                packet = prompts.information_packet(hypotheses, tests)
                packets = prompts.strategy_specific_packets(branches, hypotheses, tests)
                for branch in branches:
                    branch["hypothesis_packet"] = packets.get(branch["id"], packet)
                hypothesis_rounds.append(
                    {
                        "round_number": len(hypothesis_rounds) + 1,
                        "global_iteration": global_iteration,
                        "previous_rounds_seen": previous,
                        "updated_strategy_ids": list(updated_since_heartbeat),
                        "hypotheses": hypotheses,
                        "tests": tests,
                        "packet": packet,
                        "strategy_packets": packets,
                    }
                )
                updated_since_heartbeat = []

            due = [
                branch
                for branch in branches
                if len(branch["history"]) - branch.get("last_memory_history_count", 0) >= MEMORY_INTERVAL
            ]
            if due:
                def update_memory(branch: dict[str, Any]) -> dict[str, Any] | None:
                    start_idx = branch.get("last_memory_history_count", 0)
                    window = branch["history"][start_idx : start_idx + MEMORY_INTERVAL]
                    if len(window) < MEMORY_INTERVAL:
                        return None
                    memory = self.llm.complete(
                        role="memory_bank",
                        purpose="evolving_dfs.memory_bank",
                        prompt=prompts.memory_prompt(challenge, branch, window, window[0]["branch_iteration"], window[-1]["branch_iteration"]),
                        system_prompt=prompts.system_prompt("memory_bank"),
                    )
                    branch["memory_bank"] = memory
                    branch["last_memory_history_count"] = start_idx + len(window)
                    return {
                        "main_strategy_id": branch["id"],
                        "branch_version": branch["branch_version"],
                        "global_iteration": global_iteration,
                        "branch_iteration_start": window[0]["branch_iteration"],
                        "branch_iteration_end": window[-1]["branch_iteration"],
                        "memory_bank": memory,
                    }

                memory_agents.extend(run_parallel(due, update_memory))
                decisions = self._run_pqf(challenge, due, branches)
                pqf_decisions.extend(decisions)
                updates = [d for d in decisions if d.get("decision") == "update"]
                if updates:
                    replacements = self._generate_strategy_updates(challenge, updates, branches, archives)
                    restarted_branches: list[dict[str, Any]] = []
                    for update in updates:
                        branch = next(b for b in branches if b["id"] == update["strategy_id"])
                        replacement = replacements.get(branch["id"])
                        if not replacement:
                            continue
                        archive = self._archive_and_replace_branch(branch, replacement, update, global_iteration)
                        archives.append(archive)
                        updated_since_heartbeat.append(branch["id"])
                        restarted_branches.append(branch)
                    run_parallel(
                        restarted_branches,
                        lambda branch: self._execute_and_critique_initial(challenge, branch, strategies, global_iteration=global_iteration),
                    )

        candidates = [
            {
                "id": branch["id"],
                "main_strategy_id": branch["id"],
                "sub_strategy_text": branch["main_strategy_text"],
                "solution": branch.get("latest_solution", ""),
            }
            for branch in branches
        ]
        final_prompt = prompts.final_judge_prompt(challenge, candidates)
        judge = self.llm.complete(
            role="final_judge",
            purpose="evolving_dfs.final_judge",
            prompt=final_prompt,
            system_prompt=prompts.system_prompt("final_judge"),
        )
        result = {
            "strategies": strategies,
            "active_branches": branches,
            "hypothesis_rounds": hypothesis_rounds,
            "replacement_archive": archives,
            "pqf_decisions": pqf_decisions,
            "memory_bank_agents": memory_agents,
            "structured_solution_pool_agents": self.record["artifacts"].get("structured_solution_pool_agents", []),
            "final": {
                "judge_response": judge,
                "candidates": candidates,
                "final_judge_input": final_prompt,
            },
        }
        self.record["artifacts"].update(result)
        return result

    def _generate_main_strategies(self, challenge: str, count: int) -> list[dict[str, Any]]:
        parsed = self.llm.structured(
            role="initial_strategy",
            purpose="deepthink.initial_strategy_generation",
            instructions=prompts.JSON_ONLY,
            prompt=prompts.strategy_generation_prompt(challenge, count),
            schema=STRATEGIES_SCHEMA,
            system_prompt=prompts.system_prompt("initial_strategy"),
        )
        strategies = parsed.get("strategies") or []
        if len(strategies) < count:
            raise ValueError(f"Initial Strategy Generator returned {len(strategies)} strategies, expected {count}")
        if len(strategies) > count:
            self.record.setdefault("events", []).append({"kind": "model_output_overrun", "message": "Extra strategies ignored", "expected": count, "actual": len(strategies)})
        return [{"id": f"main{idx + 1}", "text": str(text), "slot_index": idx, "branch_version": 1} for idx, text in enumerate(strategies[:count])]

    def _build_branches(self, challenge: str, strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def build_for_strategy(strategy: dict[str, Any]) -> list[dict[str, Any]]:
            if self.config.sub_strategies:
                parsed = self.llm.structured(
                    role="sub_strategy",
                    purpose="deepthink.sub_strategy_generation",
                    instructions=prompts.JSON_ONLY,
                    prompt=prompts.sub_strategy_prompt(challenge, strategy, strategies, self.config.sub_strategies),
                    schema=SUB_STRATEGIES_SCHEMA,
                    system_prompt=prompts.system_prompt("sub_strategy"),
                )
                sub_strategies = parsed.get("sub_strategies") or []
                if len(sub_strategies) < self.config.sub_strategies:
                    raise ValueError("Sub-Strategy Generator returned fewer sub-strategies than requested")
            else:
                sub_strategies = [strategy["text"]]
            strategy_branches = []
            for sub_idx, sub_text in enumerate(sub_strategies[: max(1, self.config.sub_strategies)]):
                strategy_branches.append(
                    {
                        "id": f"{strategy['id']}-sub{sub_idx + 1}" if self.config.sub_strategies else strategy["id"],
                        "main_strategy_id": strategy["id"],
                        "main_strategy_text": strategy["text"],
                        "sub_strategy_text": str(sub_text),
                        "branch_version": strategy.get("branch_version", 1),
                    }
                )
            return strategy_branches

        branches = []
        for strategy_branches in run_parallel(strategies, build_for_strategy):
            branches.extend(strategy_branches)
        return branches

    def _strategy_context(self, strategies: list[dict[str, Any]]) -> str:
        return "\n\n".join(f"{strategy['id']}: {strategy['text']}" for strategy in strategies)

    def _hypothesis_round(
        self,
        challenge: str,
        strategies: list[dict[str, Any]],
        *,
        round_number: int,
        global_iteration: int,
        selective: bool | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, str], str, dict[str, str]]:
        if self.config.hypotheses == 0:
            return [], {}, prompts.information_packet([], {}), {}
        mode = "selective_injection" if selective else self.config.hypothesis_injection_mode
        context = "" if mode == "parallel" else self._strategy_context(strategies)
        prompt = prompts.hypothesis_generation_prompt(challenge, self.config.hypotheses, mode, context)
        hypotheses = self._generate_hypotheses_from_prompt(prompt, round_number=round_number, global_iteration=global_iteration)
        tests = self._test_hypotheses(challenge, hypotheses)
        packet = prompts.information_packet(hypotheses, tests)
        packets = prompts.strategy_specific_packets(strategies, hypotheses, tests) if mode == "selective_injection" else {s["id"]: packet for s in strategies}
        return hypotheses, tests, packet, packets

    def _generate_hypotheses_from_prompt(self, prompt: str, *, round_number: int, global_iteration: int) -> list[dict[str, Any]]:
        parsed = self.llm.structured(
            role="hypothesis_generation",
            purpose="deepthink.hypothesis_generation",
            instructions=prompts.JSON_ONLY,
            prompt=prompt,
            schema=HYPOTHESES_SCHEMA,
            system_prompt=prompts.system_prompt("hypothesis_generation"),
        )
        raw = parsed.get("hypotheses") or []
        if len(raw) < self.config.hypotheses:
            raise ValueError("Hypothesis Generator returned fewer hypotheses than requested")
        result = []
        for idx, item in enumerate(raw[: self.config.hypotheses], 1):
            if isinstance(item, str):
                text = item
                targets: list[str] = []
            else:
                text = str(item.get("text") or item.get("hypothesis") or "")
                targets = [str(t) for t in item.get("target_strategies", [])]
            result.append(
                {
                    "id": f"h{round_number}-{idx}",
                    "text": text,
                    "target_strategy_ids": targets,
                    "round_number": round_number,
                    "global_iteration": global_iteration,
                }
            )
        return result

    def _test_hypotheses(self, challenge: str, hypotheses: list[dict[str, Any]]) -> dict[str, str]:
        def test_one(hyp: dict[str, Any]) -> tuple[str, str]:
            return hyp["id"], self.llm.complete(
                role="hypothesis_testing",
                purpose="deepthink.hypothesis_testing",
                prompt=prompts.hypothesis_test_prompt(challenge, hyp),
                system_prompt=prompts.system_prompt("hypothesis_testing"),
            )

        return dict(run_parallel(hypotheses, test_one))

    def _new_evolving_branch(self, strategy: dict[str, Any], index: int, packet: str) -> dict[str, Any]:
        return {
            "id": strategy["id"],
            "main_strategy_id": strategy["id"],
            "main_strategy_text": strategy["text"],
            "sub_strategy_text": strategy["text"],
            "slot_index": index - 1,
            "branch_version": 1,
            "branch_iteration_count": 0,
            "global_iteration": 0,
            "history": [],
            "pool_history": [],
            "memory_bank": None,
            "last_memory_history_count": 0,
            "hypothesis_packet": packet,
            "replacement_history": [],
        }

    def _execute_and_critique_initial(self, challenge: str, branch: dict[str, Any], strategies: list[dict[str, Any]], *, global_iteration: int) -> None:
        branch["branch_iteration_count"] = 1
        branch["global_iteration"] = global_iteration
        execution = self.llm.complete(
            role="solution_attempt",
            purpose="evolving_dfs.solution_attempt",
            prompt=prompts.execution_prompt(challenge, branch, strategies, branch.get("hypothesis_packet", "")),
            system_prompt=prompts.system_prompt("solution_attempt"),
        )
        critique = self.llm.complete(
            role="solution_critique",
            purpose="evolving_dfs.initial_solution_critique",
            prompt=prompts.critique_prompt(challenge, branch, execution),
            system_prompt=prompts.system_prompt("solution_critique"),
        )
        branch["latest_solution"] = execution
        branch["latest_critique"] = critique
        branch["history"] = [
            {
                "global_iteration": global_iteration,
                "branch_iteration": 1,
                "branch_version": branch["branch_version"],
                "label": "initial_execution",
                "solution": execution,
                "critique": critique,
                "timestamp": utc_now_iso(),
            }
        ]

    def _run_solution_pool(self, challenge: str, branch: dict[str, Any], branches: list[dict[str, Any]], *, global_iteration: int) -> None:
        parsed = self.llm.structured(
            role="structured_solution_pool",
            purpose="evolving_dfs.structured_solution_pool",
            instructions=prompts.JSON_ONLY,
            prompt=prompts.solution_pool_prompt(challenge, branch, branches, branch.get("hypothesis_packet", ""), global_iteration),
            schema=SOLUTION_POOL_SCHEMA,
            system_prompt=prompts.system_prompt("structured_solution_pool"),
        )
        solutions = parsed.get("solutions") or []
        if len(solutions) < 5:
            raise ValueError("Structured Solution Pool Agent returned fewer than five entries")
        pool_response = dumps({"strategy_id": branch["id"], "solutions": solutions[:5]})
        entry = {
            "global_iteration": global_iteration,
            "branch_iteration": branch.get("branch_iteration_count", 1),
            "pool_response": pool_response,
            "parsed_pool_response": {"strategy_id": branch["id"], "solutions": solutions[:5]},
        }
        branch.setdefault("pool_history", []).append(entry)
        branch["latest_pool"] = pool_response
        with self._lock:
            self.record["artifacts"].setdefault("structured_solution_pool_agents", []).append(
                {
                    "main_strategy_id": branch["id"],
                    "branch_version": branch["branch_version"],
                    "global_iteration": global_iteration,
                    "branch_iteration": branch.get("branch_iteration_count", 1),
                    "parsed_pool_response": entry["parsed_pool_response"],
                }
            )

    def _run_pqf(self, challenge: str, due: list[dict[str, Any]], branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups = [due[i : i + PQF_GROUP_SIZE] for i in range(0, len(due), PQF_GROUP_SIZE)]
        indexed_groups = list(enumerate(groups))

        def run_group(item: tuple[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
            index, group = item
            parsed = self.llm.structured(
                role="post_quality_filter",
                purpose="evolving_dfs.post_quality_filter",
                instructions=prompts.JSON_ONLY,
                prompt=prompts.pqf_prompt(challenge, index, len(groups), group, branches, self.config.pqf_aggressiveness),
                schema=PQF_SCHEMA,
                system_prompt=prompts.system_prompt("post_quality_filter"),
            )
            return parsed.get("strategies") or []

        decisions: list[dict[str, Any]] = []
        for group_decisions in run_parallel(indexed_groups, run_group):
            decisions.extend(group_decisions)
        return decisions

    def _generate_strategy_updates(self, challenge: str, updates: list[dict[str, Any]], branches: list[dict[str, Any]], archives: list[dict[str, Any]]) -> dict[str, str]:
        parsed = self.llm.structured(
            role="initial_strategy",
            purpose="evolving_dfs.strategy_update",
            instructions=prompts.JSON_ONLY,
            prompt=prompts.strategy_update_prompt(challenge, updates, branches, archives),
            schema=STRATEGY_UPDATE_SCHEMA,
            system_prompt=prompts.system_prompt("strategy_update"),
        )
        result = {}
        for item in parsed.get("strategies") or []:
            result[str(item.get("strategy_id"))] = str(item.get("strategy"))
        return result

    def _archive_and_replace_branch(self, branch: dict[str, Any], replacement: str, decision: dict[str, Any], global_iteration: int) -> dict[str, Any]:
        archive = {
            "strategy_id": branch["id"],
            "previous_strategy_text": branch["main_strategy_text"],
            "replacement_strategy_text": replacement,
            "replaced_at_global_iteration": global_iteration,
            "previous_branch_version": branch["branch_version"],
            "new_branch_version": branch["branch_version"] + 1,
            "pqf_reasoning": decision.get("reasoning", ""),
            "memory_bank": branch.get("memory_bank"),
            "latest_solution": branch.get("latest_solution"),
            "latest_critique": branch.get("latest_critique"),
            "branch_history": list(branch.get("history", [])),
            "pool_history": list(branch.get("pool_history", [])),
        }
        branch.setdefault("replacement_history", []).append(archive)
        branch["branch_version"] += 1
        branch["main_strategy_text"] = replacement
        branch["sub_strategy_text"] = replacement
        branch["branch_iteration_count"] = 0
        branch["history"] = []
        branch["pool_history"] = []
        branch["latest_pool"] = None
        branch["memory_bank"] = None
        branch["last_memory_history_count"] = 0
        branch["hypothesis_packet"] = f"<FlushedHypothesisPacket strategyId=\"{branch['id']}\" flushedAtGlobalIteration=\"{global_iteration}\" />"
        branch["last_hypothesis_flush_global_iteration"] = global_iteration
        return archive
