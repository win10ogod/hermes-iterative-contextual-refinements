"""Dynamic Compute Alternatives engine."""

from __future__ import annotations

from typing import Any

from .concurrency import run_parallel
from .config import ICRConfig
from .json_utils import utc_now_iso
from .llm import ICRLlm
from .schemas import DCA_LOCAL_SCHEMA, DCA_POOL_SCHEMA


POOL_GENERATOR_PROMPT = "You are the DCA Pool Generator. Produce orthogonal high-level solution alternatives with priority 2-5."
LOCAL_POOL_PROMPT = "You are a DCA Local Pool Agent. Evolve the assigned solution locally into concrete child alternatives."


class DCAEngine:
    def __init__(self, llm: ICRLlm, record: dict[str, Any], config: ICRConfig):
        self.llm = llm
        self.record = record
        self.config = config

    def run(self, problem: str) -> dict[str, Any]:
        state: dict[str, Any] = {
            "problem": problem,
            "status": "processing",
            "solutions": [{"id": "root", "title": "Problem", "content": problem, "type": "root", "timestamp": utc_now_iso()}],
        }
        pool = self.llm.structured(
            role="dca_pool_generator",
            purpose="dca.pool_generator",
            instructions="Return JSON with a solutions array.",
            prompt=f"Problem:\n{problem}\n\nGenerate up to {self.config.dca_pool_limit} orthogonal solutions.",
            schema=DCA_POOL_SCHEMA,
            system_prompt=POOL_GENERATOR_PROMPT,
        )
        layer = []
        for idx, item in enumerate((pool.get("solutions") or [])[: self.config.dca_pool_limit]):
            priority = int(item.get("priority", 2) or 2)
            priority = min(max(priority, 2), 5)
            solution = {
                "id": f"ortho-{idx}",
                "title": str(item.get("title", f"Alternative {idx + 1}")),
                "content": str(item.get("content", "")),
                "priority": priority,
                "parentId": "root",
                "type": "orthogonal",
                "timestamp": utc_now_iso(),
            }
            layer.append(solution)
            state["solutions"].append(solution)

        def evolve_solution(solution: dict[str, Any]) -> list[dict[str, Any]]:
            full_pool = "\n\n".join(
                f"[ID: {other['id']}] {other['title']}: {other['content']}"
                for other in layer
                if other["id"] != solution["id"]
            )
            local = self.llm.structured(
                role="dca_local_pool_agent",
                purpose="dca.local_pool_agent",
                instructions="Return JSON with an evolutions array.",
                prompt=(
                    f"Problem:\n{problem}\n\nAssigned solution {solution['id']} priority {solution['priority']}:\n"
                    f"{solution['title']}: {solution['content']}\n\nFull peer pool:\n{full_pool}\n\n"
                    f"Generate {solution['priority']} local evolutions."
                ),
                schema=DCA_LOCAL_SCHEMA,
                system_prompt=LOCAL_POOL_PROMPT,
            )
            children = []
            for evo_idx, evo in enumerate((local.get("evolutions") or [])[: solution["priority"]]):
                children.append(
                    {
                        "id": f"{solution['id']}-evo-{evo_idx}",
                        "title": str(evo.get("title", f"Evolution {evo_idx + 1}")),
                        "content": str(evo.get("content", "")),
                        "parentId": solution["id"],
                        "type": "evolution",
                        "timestamp": utc_now_iso(),
                    }
                )
            return children

        for children in run_parallel(layer, evolve_solution):
            state["solutions"].extend(children)
        state["status"] = "completed"
        self.record["artifacts"].update({"dca_state": state, "final": {"solutions": state["solutions"]}})
        return state
