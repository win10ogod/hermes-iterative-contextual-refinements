"""Contextual refinement engine."""

from __future__ import annotations

from typing import Any

from .config import ICRConfig
from .llm import ICRLlm
from .json_utils import utc_now_iso


MAIN_GENERATOR_PROMPT = "You are the Main Generator in an iterative refinement system. Produce the best current generation and incorporate critique and strategic pool guidance."
ITERATIVE_AGENT_PROMPT = "You are the Iterative Agent. Critique the current generation for flaws, gaps, errors, and missed opportunities. Do not fix it."
STRATEGIC_POOL_PROMPT = "You are the Strategic Pool Agent. Evolve a pool of unexplored strategies and radical alternatives based on the generation and critique. Return <<<Exit>>> only after repeated no-flaw critiques show completion."
MEMORY_AGENT_PROMPT = "You are the Memory Agent. Condense recent iterations into what worked, what failed, persistent issues, useful techniques, and guidance for future generations."


class ContextualRefinementEngine:
    def __init__(self, llm: ICRLlm, record: dict[str, Any], config: ICRConfig):
        self.llm = llm
        self.record = record
        self.config = config

    def run(self, request: str) -> dict[str, Any]:
        state: dict[str, Any] = {
            "initial_user_request": request,
            "initial_main_generation": "",
            "current_best_generation": "",
            "current_best_suggestions": "",
            "all_iterative_suggestions": [],
            "main_generator_history": [{"role": "user", "content": f"Initial User Request:\n{request}"}],
            "iterative_agent_history": [{"role": "user", "content": f"Initial User Request:\n{request}"}],
            "strategic_pool_agent_history": [{"role": "user", "content": f"Initial User Request:\n{request}"}],
            "memory_agent_history": [],
            "current_memory": "",
            "memory_snapshots": [],
            "current_strategic_pool": "",
            "all_strategic_pools": [],
            "iteration_count": 0,
            "messages": [],
            "content_history": [],
            "status": "processing",
        }
        turns_since_condense = 0
        for iteration in range(1, self.config.contextual_iterations + 1):
            state["iteration_count"] = iteration
            main_prompt = self._history_prompt(state["main_generator_history"])
            main = self.llm.complete(
                role="contextual_main_generator",
                purpose="contextual.main_generator",
                prompt=main_prompt,
                system_prompt=MAIN_GENERATOR_PROMPT,
            )
            if iteration == 1:
                state["initial_main_generation"] = main
            state["current_best_generation"] = main
            state["content_history"].append({"content": main, "title": f"Iteration {iteration} - Main Generation", "timestamp": utc_now_iso()})
            state["messages"].append({"role": "main_generator", "content": main, "iteration_number": iteration, "timestamp": utc_now_iso()})
            state["main_generator_history"].append({"role": "assistant", "content": main})
            state["iterative_agent_history"].append({"role": "assistant", "content": main})

            state["iterative_agent_history"].append({"role": "user", "content": "Please critique the solution and tool executions you just generated above. If no tools were used, critique the generation text."})
            critique = self.llm.complete(
                role="contextual_iterative_agent",
                purpose="contextual.iterative_agent",
                prompt=self._history_prompt(state["iterative_agent_history"]),
                system_prompt=ITERATIVE_AGENT_PROMPT,
            )
            state["current_best_suggestions"] = critique
            state["all_iterative_suggestions"].append(critique)
            state["messages"].append({"role": "iterative_agent", "content": critique, "iteration_number": iteration, "timestamp": utc_now_iso()})
            state["iterative_agent_history"].append({"role": "assistant", "content": critique})

            strategic_observation = "\n".join(
                [
                    "## Observation: Current Main Generation",
                    main,
                    "",
                    "## Observation: Solution Critique",
                    critique,
                    "",
                    "## Strategic Pool Evolution Task",
                    "Update and evolve a pool of strategies that push exploration further.",
                ]
            )
            state["strategic_pool_agent_history"].append({"role": "user", "content": strategic_observation})
            pool = self.llm.complete(
                role="contextual_strategic_pool_agent",
                purpose="contextual.strategic_pool_agent",
                prompt=self._history_prompt(state["strategic_pool_agent_history"]),
                system_prompt=STRATEGIC_POOL_PROMPT,
            )
            if pool.strip() == "<<<Exit>>>":
                state["messages"].append({"role": "system", "content": "Strategic Pool Agent requested exit.", "iteration_number": iteration, "timestamp": utc_now_iso()})
                break
            state["current_strategic_pool"] = pool
            state["all_strategic_pools"].append(pool)
            state["messages"].append({"role": "strategic_pool_agent", "content": pool, "iteration_number": iteration, "timestamp": utc_now_iso()})
            state["strategic_pool_agent_history"].append({"role": "assistant", "content": pool})

            combined = "\n\n".join([critique, "---", "## Strategic Pool", pool])
            state["main_generator_history"].append({"role": "user", "content": combined})
            turns_since_condense += 1

            if turns_since_condense >= self.config.contextual_condensation_interval:
                memory_prompt = self._memory_prompt(state)
                memory = self.llm.complete(
                    role="contextual_memory_agent",
                    purpose="contextual.memory_agent",
                    prompt=memory_prompt,
                    system_prompt=MEMORY_AGENT_PROMPT,
                )
                state["current_memory"] = memory
                state["memory_snapshots"].append({"memory": memory, "final_generation": state["current_best_generation"], "condense_point": iteration})
                state["messages"].append({"role": "memory_agent", "content": memory, "iteration_number": iteration, "timestamp": utc_now_iso()})
                initial = {"role": "user", "content": f"Initial User Request:\n{request}"}
                memory_msg = {"role": "user", "content": f"Memory Summary (What worked and what didn't):\n{memory}"}
                latest = {"role": "assistant", "content": main}
                state["main_generator_history"] = [initial, memory_msg, latest, {"role": "user", "content": combined}]
                state["iterative_agent_history"] = [initial, memory_msg, latest, {"role": "assistant", "content": critique}]
                state["strategic_pool_agent_history"] = [initial, memory_msg, {"role": "assistant", "content": pool}]
                turns_since_condense = 0

            state["main_generator_history"].append({"role": "user", "content": "Now implement the next iteration of the solution based on the critique and the strategies you just generated above."})

        state["status"] = "completed"
        self.record["artifacts"].update({"contextual_state": state, "final": {"content": state["current_best_generation"], "strategic_pool": state["current_strategic_pool"]}})
        return state

    def _history_prompt(self, history: list[dict[str, str]]) -> str:
        return "\n\n".join(f"{item['role'].upper()}:\n{item['content']}" for item in history)

    def _memory_prompt(self, state: dict[str, Any]) -> str:
        recent = [
            f"[Iteration {m['iteration_number']}] {m['role']}:\n{m['content']}"
            for m in state["messages"]
            if m["role"] in {"main_generator", "iterative_agent"}
        ]
        snapshots = [
            f"Memory V{idx + 1}:\n{s['memory']}\n\nFinal Main Generation after Memory V{idx + 1}:\n{s['final_generation']}"
            for idx, s in enumerate(state["memory_snapshots"])
        ]
        return "\n\n".join(
            [
                f"Initial User Request:\n{state['initial_user_request']}",
                *snapshots,
                "Recent Iterations to Analyze:",
                *recent,
                "Task: Create an evolving memory document summarizing what worked and what did not.",
            ]
        )

