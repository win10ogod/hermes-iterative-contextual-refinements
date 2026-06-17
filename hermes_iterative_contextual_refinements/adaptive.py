"""Adaptive Deepthink tool-interface engine."""

from __future__ import annotations

from typing import Any

from . import prompts
from .concurrency import run_parallel
from .config import ICRConfig
from .deepthink import DeepthinkEngine
from .llm import ICRLlm
from .schemas import ADAPTIVE_ORCHESTRATOR_SCHEMA
from .source_prompts import load_adaptive_prompts


ADAPTIVE_TOOLS = [
    {
        "name": "GenerateStrategies",
        "description": "Generate high-level strategic interpretations of the challenge.",
        "parameters": {"numStrategies": "positive integer", "specialContext": "optional string"},
    },
    {
        "name": "GenerateHypotheses",
        "description": "Generate testable hypotheses that can inform later strategy execution.",
        "parameters": {"numHypotheses": "positive integer", "specialContext": "optional string"},
    },
    {
        "name": "TestHypotheses",
        "description": "Test one or more hypotheses and return evidence for each.",
        "parameters": {"hypothesisIds": "array of ids", "specialContext": "optional string"},
    },
    {
        "name": "ExecuteStrategies",
        "description": "Execute strategies with selected tested hypotheses.",
        "parameters": {"executions": [{"strategyId": "id", "hypothesisIds": ["id"]}], "specialContext": "optional string"},
    },
    {
        "name": "SolutionCritique",
        "description": "Critique one or more executions or corrected solutions.",
        "parameters": {"executionIds": "array of ids", "specialContext": "optional string"},
    },
    {
        "name": "CorrectedSolutions",
        "description": "Produce corrected solutions for critiqued executions.",
        "parameters": {"executionIds": "array of ids"},
    },
    {
        "name": "SelectBestSolution",
        "description": "Compare candidates and select the strongest final answer.",
        "parameters": {"solutionIds": "array of ids"},
    },
    {"name": "Exit", "description": "Finish after a final solution has been selected.", "parameters": {"note": "optional string"}},
]

ADAPTIVE_ORCHESTRATOR_PROMPT = load_adaptive_prompts()["main"]


class AdaptiveDeepthinkEngine:
    def __init__(self, llm: ICRLlm, record: dict[str, Any], config: ICRConfig):
        self.llm = llm
        self.record = record
        self.config = config
        self.helper = DeepthinkEngine(llm, record, config)
        self.state: dict[str, Any] = {
            "id": f"adaptive-core-{self.record.get('run_id', 'run')}",
            "question": "",
            "status": "idle",
            "error": None,
            "strategies": {},
            "hypotheses": {},
            "hypothesis_testings": {},
            "executions": {},
            "critiques": {},
            "corrected_solutions": {},
            "selected_solution": None,
            "should_exit": False,
            "tool_events": [],
        }

    def run(self, challenge: str) -> dict[str, Any]:
        self.state["question"] = challenge
        self.state["status"] = "processing"
        for turn in range(1, self.config.adaptive_max_tool_turns + 1):
            decision = self.llm.structured(
                role="adaptive_orchestrator",
                purpose="adaptive_deepthink.orchestrator",
                instructions=prompts.JSON_ONLY,
                prompt=self._orchestrator_prompt(challenge),
                schema=ADAPTIVE_ORCHESTRATOR_SCHEMA,
                system_prompt=ADAPTIVE_ORCHESTRATOR_PROMPT,
            )
            tool_calls = decision.get("tool_calls") or []
            if not tool_calls and self.state.get("selected_solution"):
                tool_calls = [{"name": "Exit", "arguments": {}}]
            for call in tool_calls:
                name = str(call.get("name"))
                args = call.get("arguments") or {}
                result = self.execute_tool(challenge, name, args)
                self.state["tool_events"].append({"turn": turn, "tool": name, "arguments": args, "result": result})
                if name == "Exit":
                    if str(result).startswith("[ERROR:"):
                        continue
                    self.state["status"] = "completed"
                    self.state["should_exit"] = True
                    self.record["artifacts"].update({"adaptive_state": self.state, "final": {"selected_solution": self.state.get("selected_solution")}})
                    return self.state
        raise RuntimeError("Adaptive Deepthink reached max tool turns before Exit")

    def _orchestrator_prompt(self, challenge: str) -> str:
        return f"""Core Challenge:
{challenge}

<Available Tools>
{ADAPTIVE_TOOLS}
</Available Tools>

<Current Adaptive State>
{self._state_summary()}
</Current Adaptive State>

Return JSON:
{{"assistant_text":"short visible note","tool_calls":[{{"name":"GenerateStrategies","arguments":{{"numStrategies":3}}}}]}}"""

    def _state_summary(self) -> dict[str, Any]:
        return {
            "strategies": self.state["strategies"],
            "hypotheses": self.state["hypotheses"],
            "tested_hypotheses": list(self.state["hypothesis_testings"].keys()),
            "executions": list(self.state["executions"].keys()),
            "critiques": list(self.state["critiques"].keys()),
            "corrected_solutions": list(self.state["corrected_solutions"].keys()),
            "selected_solution": self.state["selected_solution"],
        }

    def execute_tool(self, challenge: str, name: str, args: dict[str, Any]) -> str:
        if name == "GenerateStrategies":
            return self._generate_strategies(challenge, int(args["numStrategies"]), str(args.get("specialContext", "")))
        if name == "GenerateHypotheses":
            return self._generate_hypotheses(challenge, int(args["numHypotheses"]), str(args.get("specialContext", "")))
        if name == "TestHypotheses":
            return self._test_hypotheses(challenge, [str(x) for x in args["hypothesisIds"]], str(args.get("specialContext", "")))
        if name == "ExecuteStrategies":
            return self._execute_strategies(challenge, args["executions"], str(args.get("specialContext", "")))
        if name == "SolutionCritique":
            return self._critique_solutions(challenge, [str(x) for x in args["executionIds"]], str(args.get("specialContext", "")))
        if name == "CorrectedSolutions":
            return self._correct_solutions(challenge, [str(x) for x in args["executionIds"]])
        if name == "SelectBestSolution":
            return self._select_best(challenge, [str(x) for x in args["solutionIds"]])
        if name == "Exit":
            if not self.state.get("selected_solution"):
                return "[ERROR: Exit rejected because no final solution has been selected]"
            return "<Adaptive Deepthink Exit />"
        return f"[ERROR: Unknown Adaptive Deepthink tool: {name}]"

    def _generate_strategies(self, challenge: str, count: int, special: str) -> str:
        parsed = self.llm.structured(
            role="initial_strategy",
            purpose="adaptive_deepthink.GenerateStrategies",
            instructions=prompts.JSON_ONLY,
            prompt=prompts.strategy_generation_prompt(challenge + _special(special), count),
            schema={"type": "object", "properties": {"strategies": {"type": "array", "items": {"type": "string"}}}, "required": ["strategies"]},
            system_prompt=prompts.system_prompt("initial_strategy"),
        )
        lines = ["<Strategies Generated>"]
        for idx, strategy in enumerate((parsed.get("strategies") or [])[:count], 1):
            sid = f"strategy-{len(self.state['strategies']) + 1}"
            self.state["strategies"][sid] = {"text": str(strategy)}
            lines.append(f"<Strategy ID: {sid}>\n{strategy}\n</Strategy ID: {sid}>")
        lines.append("</Strategies Generated>")
        return "\n\n".join(lines)

    def _generate_hypotheses(self, challenge: str, count: int, special: str) -> str:
        parsed = self.llm.structured(
            role="hypothesis_generation",
            purpose="adaptive_deepthink.GenerateHypotheses",
            instructions=prompts.JSON_ONLY,
            prompt=prompts.hypothesis_generation_prompt(challenge + _special(special), count, "strategy_aware", str(self.state["strategies"])),
            schema={"type": "object", "properties": {"hypotheses": {"type": "array"}}, "required": ["hypotheses"]},
            system_prompt=prompts.system_prompt("hypothesis_generation"),
        )
        lines = ["<Hypotheses Generated>"]
        for item in (parsed.get("hypotheses") or [])[:count]:
            text = item if isinstance(item, str) else item.get("text") or item.get("hypothesis")
            hid = f"hypothesis-{len(self.state['hypotheses']) + 1}"
            self.state["hypotheses"][hid] = {"text": str(text)}
            lines.append(f"<Hypothesis ID: {hid}>\n{text}\n</Hypothesis ID: {hid}>")
        lines.append("</Hypotheses Generated>")
        return "\n\n".join(lines)

    def _test_hypotheses(self, challenge: str, ids: list[str], special: str) -> str:
        lines = ["<Hypothesis Testing Results>"]

        def test_one(hid: str) -> tuple[str, dict[str, str] | None]:
            hyp = self.state["hypotheses"].get(hid)
            if not hyp:
                return f"<{hid}>[ERROR: Hypothesis not found]</{hid}>", None
            text = self.llm.complete(
                role="hypothesis_testing",
                purpose="adaptive_deepthink.TestHypotheses",
                prompt=prompts.hypothesis_test_prompt(challenge + _special(special), {"id": hid, "text": hyp["text"]}),
                system_prompt=prompts.system_prompt("hypothesis_testing"),
            )
            return (
                f"<{hid}>\n<Actual Hypothesis>{hyp['text']}</Actual Hypothesis>\n<Hypothesis Testing>{text}</Hypothesis Testing>\n</{hid}>",
                {"id": hid, "hypothesis": hyp["text"], "testing": text},
            )

        for line, state_update in run_parallel(ids, test_one):
            lines.append(line)
            if state_update:
                self.state["hypothesis_testings"][state_update["id"]] = {
                    "hypothesis": state_update["hypothesis"],
                    "testing": state_update["testing"],
                }
        lines.append("</Hypothesis Testing Results>")
        return "\n\n".join(lines)

    def _execute_strategies(self, challenge: str, executions: list[dict[str, Any]], special: str) -> str:
        lines = ["<Strategy Executions>"]
        strategy_list = [{"id": sid, "text": data["text"]} for sid, data in self.state["strategies"].items()]

        def execute_one(item: dict[str, Any]) -> tuple[str, tuple[str, dict[str, str]] | None]:
            sid = str(item["strategyId"])
            strategy = self.state["strategies"].get(sid)
            if not strategy:
                return f"<Execution ID: execution-{sid}>[ERROR: Strategy not found]</Execution ID: execution-{sid}>", None
            packet = self._packet_for(item.get("hypothesisIds", []))
            branch = {"id": sid, "main_strategy_id": sid, "main_strategy_text": strategy["text"], "sub_strategy_text": strategy["text"]}
            text = self.llm.complete(
                role="solution_attempt",
                purpose="adaptive_deepthink.ExecuteStrategies",
                prompt=prompts.execution_prompt(challenge + _special(special), branch, strategy_list, packet),
                system_prompt=prompts.system_prompt("solution_attempt"),
            )
            eid = f"execution-{sid}"
            return f"<Execution ID: {eid}>\n{text}\n</Execution ID: {eid}>", (eid, {"strategy": strategy["text"], "execution": text})

        for line, state_update in run_parallel(executions, execute_one):
            lines.append(line)
            if state_update:
                eid, data = state_update
                self.state["executions"][eid] = data
        lines.append("</Strategy Executions>")
        return "\n\n".join(lines)

    def _critique_solutions(self, challenge: str, ids: list[str], special: str) -> str:
        lines = ["<Solution Critiques>"]

        def critique_one(eid: str) -> tuple[str, tuple[str, dict[str, str]] | None]:
            execution = self.state["executions"].get(eid) or self.state["corrected_solutions"].get(eid)
            if not execution:
                return f"<{eid}: Critique>[ERROR: Execution not found]</{eid}: Critique>", None
            solution = execution.get("execution") or execution.get("correctedSolution", "")
            branch = {"main_strategy_id": eid, "main_strategy_text": execution["strategy"]}
            critique = self.llm.complete(
                role="solution_critique",
                purpose="adaptive_deepthink.SolutionCritique",
                prompt=prompts.critique_prompt(challenge + _special(special), branch, solution),
                system_prompt=prompts.system_prompt("solution_critique"),
            )
            return f"<{eid}: Critique>\n{critique}\n</{eid}: Critique>", (eid, {"critique": critique})

        for line, state_update in run_parallel(ids, critique_one):
            lines.append(line)
            if state_update:
                eid, data = state_update
                self.state["critiques"][eid] = data
        lines.append("</Solution Critiques>")
        return "\n\n".join(lines)

    def _correct_solutions(self, challenge: str, ids: list[str]) -> str:
        lines = ["<Corrected Solutions>"]

        def correct_one(eid: str) -> tuple[str, tuple[str, dict[str, str]] | None]:
            execution = self.state["executions"].get(eid)
            critique = self.state["critiques"].get(eid)
            if not execution or not critique:
                return f"<{eid}:Corrected>[ERROR: Execution or critique not found]</{eid}:Corrected>", None
            branch = {"main_strategy_id": eid, "main_strategy_text": execution["strategy"]}
            corrected = self.llm.complete(
                role="self_improvement",
                purpose="adaptive_deepthink.CorrectedSolutions",
                prompt=prompts.correction_prompt(challenge, branch, execution["execution"], critique["critique"]),
                system_prompt=prompts.system_prompt("self_improvement"),
            )
            cid = f"{eid}:Corrected"
            return f"<{cid}>\n{corrected}\n</{cid}>", (cid, {"strategy": execution["strategy"], "correctedSolution": corrected})

        for line, state_update in run_parallel(ids, correct_one):
            lines.append(line)
            if state_update:
                cid, data = state_update
                self.state["corrected_solutions"][cid] = data
        lines.append("</Corrected Solutions>")
        return "\n\n".join(lines)

    def _select_best(self, challenge: str, ids: list[str]) -> str:
        candidates = []
        for sid in ids:
            solution = self.state["corrected_solutions"].get(sid)
            if solution:
                candidates.append({"id": sid, "main_strategy_id": sid, "sub_strategy_text": solution["strategy"], "solution": solution["correctedSolution"]})
        if not candidates:
            raise ValueError("SelectBestSolution received no valid candidate ids")
        final_prompt = prompts.final_judge_prompt(challenge, candidates)
        selected = self.llm.complete(
            role="final_judge",
            purpose="adaptive_deepthink.SelectBestSolution",
            prompt=final_prompt,
            system_prompt=prompts.system_prompt("final_judge"),
        )
        self.state["selected_solution"] = selected
        return f"<Best Solution Selected>\n{selected}\n</Best Solution Selected>"

    def _packet_for(self, ids: list[str]) -> str:
        entries = []
        for hid in ids:
            result = self.state["hypothesis_testings"].get(hid)
            if result:
                entries.append(f"<Hypothesis id=\"{hid}\">\n{result['hypothesis']}\n{result['testing']}\n</Hypothesis>")
        return "<Full Information Packet>\n" + "\n\n".join(entries) + "\n</Full Information Packet>"


def _special(value: str) -> str:
    return f"\n\n<Special Context>\n{value}\n</Special Context>" if value else ""
