"""Dynamic Compute Alternatives engine."""

from __future__ import annotations

from typing import Any

from .concurrency import run_parallel
from .config import ICRConfig
from .json_utils import utc_now_iso
from .llm import ICRLlm
from .schemas import DCA_LOCAL_SCHEMA, DCA_POOL_SCHEMA
from .source_prompts import load_dca_prompts


_DCA_SOURCE_PROMPTS = load_dca_prompts()
POOL_GENERATOR_PROMPT = _DCA_SOURCE_PROMPTS["pool_generator"]
LOCAL_POOL_PROMPT = _DCA_SOURCE_PROMPTS["local_pool_agent"]


class DCAEngine:
    def __init__(self, llm: ICRLlm, record: dict[str, Any], config: ICRConfig):
        self.llm = llm
        self.record = record
        self.config = config

    def run(self, problem: str) -> dict[str, Any]:
        state: dict[str, Any] = {
            "id": f"dca-{self.record.get('run_id', 'run')}",
            "problem": problem,
            "status": "processing",
            "error": None,
            "is_stop_requested": False,
            "solutions": [{"id": "root", "title": "Problem", "content": problem, "type": "root", "timestamp": utc_now_iso()}],
        }
        pool = self.llm.structured(
            role="dca_pool_generator",
            purpose="dca.pool_generator",
            instructions="Return JSON with a solutions array.",
            prompt=problem,
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
            local_system_prompt = (
                LOCAL_POOL_PROMPT.replace("{{solutionId}}", solution["id"])
                .replace("{{priority}}", str(solution["priority"]))
                .replace("{{fullPool}}", full_pool)
            )
            local = self.llm.structured(
                role="dca_local_pool_agent",
                purpose="dca.local_pool_agent",
                instructions="Return JSON with an evolutions array.",
                prompt=f"Evolve solution {solution['id']}",
                schema=DCA_LOCAL_SCHEMA,
                system_prompt=local_system_prompt,
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
