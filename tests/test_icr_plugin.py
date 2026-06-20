from __future__ import annotations

import json
import re
import hashlib
import importlib
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from hermes_iterative_contextual_refinements.agentic import apply_operation
from hermes_iterative_contextual_refinements import adaptive as adaptive_module
from hermes_iterative_contextual_refinements import agentic as agentic_module
from hermes_iterative_contextual_refinements import contextual as contextual_module
from hermes_iterative_contextual_refinements import dca as dca_module
from hermes_iterative_contextual_refinements import prompts as prompt_module
from hermes_iterative_contextual_refinements.config import build_config
from hermes_iterative_contextual_refinements.constants import PLUGIN_NAME, PLUGIN_VERSION
from hermes_iterative_contextual_refinements.commands import parse_icr_args
from hermes_iterative_contextual_refinements import heartbeat as heartbeat_module
from hermes_iterative_contextual_refinements.llm import ICRLlm
from hermes_iterative_contextual_refinements.plugin import register
from hermes_iterative_contextual_refinements.persistence import RunStore
from hermes_iterative_contextual_refinements.progress import RunProgress
from hermes_iterative_contextual_refinements.prompt_parity import validate_prompt_parity
from hermes_iterative_contextual_refinements.python_runtime import PythonSession, extract_python_blocks
from hermes_iterative_contextual_refinements.run_record import new_run
from hermes_iterative_contextual_refinements.runner import ICRRunner
from hermes_iterative_contextual_refinements.schemas import icr_run_schema, icr_start_schema
from hermes_iterative_contextual_refinements.source_prompts import SOURCE_PROMPT_SHA256, load_adaptive_prompts, load_deepthink_prompts
from hermes_iterative_contextual_refinements.tools import make_handlers
from hermes_iterative_contextual_refinements import __version__


@dataclass
class Usage:
    input_tokens: int = 1
    output_tokens: int = 1
    total_tokens: int = 2
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None


@dataclass
class TextResult:
    text: str
    provider: str = "fake"
    model: str = "fake-model"
    agent_id: str = "default"
    usage: Usage = field(default_factory=Usage)
    audit: dict | None = None


@dataclass
class StructuredResult:
    text: str
    parsed: dict
    provider: str = "fake"
    model: str = "fake-model"
    agent_id: str = "default"
    usage: Usage = field(default_factory=Usage)
    content_type: str = "json"
    audit: dict | None = None


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.pqf_updated = False
        self.adaptive_turn = 0
        self.agentic_turn = 0

    def complete(self, messages, **kwargs):
        purpose = kwargs.get("purpose", "text")
        prompt = messages[-1]["content"]
        self.calls.append(("text", purpose, prompt))
        if purpose.endswith("final_judge") or purpose.endswith("SelectBestSolution"):
            return TextResult(f"SELECTED by {purpose}")
        if purpose == "agentic.verify_current_content":
            return TextResult("Verified: no blocking issues.")
        if purpose.startswith("contextual.main_generator"):
            return TextResult(f"Main generation {len([c for c in self.calls if c[1] == purpose])}")
        if purpose.startswith("contextual.iterative_agent"):
            return TextResult("Critique: improve specificity.")
        if purpose.startswith("contextual.strategic_pool_agent"):
            return TextResult("Strategic pool: try an orthogonal framing.")
        if purpose.startswith("contextual.memory_agent"):
            return TextResult("Memory: specificity improved; keep structural checks.")
        if "hypothesis_testing" in purpose or "TestHypotheses" in purpose:
            return TextResult("Investigation complete. Classification: VALIDATED.")
        if "solution_critique" in purpose or "SolutionCritique" in purpose:
            return TextResult(f"Critique for {purpose}: missing edge case.")
        if "solution_attempt" in purpose or "ExecuteStrategies" in purpose:
            return TextResult(f"Solution attempt for {purpose}.")
        if "self_improvement" in purpose or "CorrectedSolutions" in purpose or "solution_correction" in purpose:
            return TextResult(f"Corrected solution for {purpose}.")
        if "memory_bank" in purpose:
            return TextResult("Memory bank: invariant A; dead end B; guidance C.")
        return TextResult(f"Text response for {purpose}.")

    def complete_structured(self, *, instructions, input, json_schema=None, json_mode=False, schema_name=None, system_prompt=None, **kwargs):
        purpose = kwargs.get("purpose") or schema_name or "structured"
        prompt = input[0]["text"]
        self.calls.append(("structured", purpose, prompt))
        parsed = self._parsed_for(purpose, prompt)
        return StructuredResult(text=json.dumps(parsed), parsed=parsed)

    def _parsed_for(self, purpose: str, prompt: str) -> dict:
        if purpose == "adaptive_deepthink.orchestrator":
            self.adaptive_turn += 1
            plan = [
                {"name": "GenerateStrategies", "arguments": {"numStrategies": 1}},
                {"name": "GenerateHypotheses", "arguments": {"numHypotheses": 1}},
                {"name": "TestHypotheses", "arguments": {"hypothesisIds": ["hypothesis-1"]}},
                {"name": "ExecuteStrategies", "arguments": {"executions": [{"strategyId": "strategy-1", "hypothesisIds": ["hypothesis-1"]}]}},
                {"name": "SolutionCritique", "arguments": {"executionIds": ["execution-strategy-1"]}},
                {"name": "CorrectedSolutions", "arguments": {"executionIds": ["execution-strategy-1"]}},
                {"name": "SelectBestSolution", "arguments": {"solutionIds": ["execution-strategy-1:Corrected"]}},
                {"name": "Exit", "arguments": {}},
            ]
            return {"assistant_text": f"adaptive turn {self.adaptive_turn}", "tool_calls": [plan[self.adaptive_turn - 1]]}
        if purpose == "agentic.orchestrator":
            self.agentic_turn += 1
            plan = [
                {"name": "read_current_content", "arguments": {}},
                {"name": "multi_edit", "arguments": {"operations": [{"action": "search_and_replace", "target": "bad", "content": "good"}]}},
                {"name": "verify_current_content", "arguments": {}},
                {"name": "Exit", "arguments": {}},
            ]
            return {"assistant_text": f"agentic turn {self.agentic_turn}", "tool_calls": [plan[self.agentic_turn - 1]]}
        if "initial_strategy_generation" in purpose or purpose.endswith("GenerateStrategies"):
            count = _count_from(prompt, default=3)
            return {"strategies": [f"Strategy {i + 1}" for i in range(count)]}
        if "sub_strategy_generation" in purpose:
            count = _count_from(prompt, default=2)
            return {"sub_strategies": [f"Sub-strategy {i + 1}" for i in range(count)]}
        if "hypothesis_generation" in purpose or purpose.endswith("GenerateHypotheses"):
            count = _count_from(prompt, default=1)
            return {
                "hypotheses": [
                    {"text": f"Hypothesis {i + 1}", "target_strategies": ["main1"] if i % 2 == 0 else []}
                    for i in range(count)
                ]
            }
        if "structured_solution_pool" in purpose:
            return {
                "strategy_id": "main1",
                "solutions": [
                    {"title": f"Pool {i}", "content": f"Pool content {i}", "confidence": 0.5, "internal_critique": "check"}
                    for i in range(5)
                ],
            }
        if "post_quality_filter" in purpose:
            ids = re.findall(r'<StrategyForDecision id="([^"]+)"', prompt)
            strategies = []
            for sid in ids:
                if sid == "main1" and not self.pqf_updated:
                    strategies.append({"strategy_id": sid, "decision": "update", "reasoning": "persistent strategic failure"})
                    self.pqf_updated = True
                else:
                    strategies.append({"strategy_id": sid, "decision": "keep", "reasoning": "still useful"})
            return {"analysis_summary": "pqf", "strategies": strategies}
        if "strategy_update" in purpose:
            return {"strategies": [{"strategy_id": "main1", "strategy": "Replacement strategy for main1"}]}
        if purpose == "dca.pool_generator":
            return {
                "solutions": [
                    {"title": "Orthogonal A", "content": "A", "priority": 2},
                    {"title": "Orthogonal B", "content": "B", "priority": 2},
                ]
            }
        if purpose == "dca.local_pool_agent":
            return {"evolutions": [{"title": "Evolution 1", "content": "E1"}, {"title": "Evolution 2", "content": "E2"}]}
        return {}


def _count_from(prompt: str, default: int) -> int:
    match = re.search(r"exactly\s+(\d+)", prompt, re.IGNORECASE)
    if not match:
        match = re.search(r"Generate up to\s+(\d+)", prompt, re.IGNORECASE)
    return int(match.group(1)) if match else default


class FakeCtx:
    def __init__(self, llm=None):
        self.llm = llm or FakeLLM()
        self.tools = {}
        self.commands = {}
        self.skills = {}

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def register_command(self, **kwargs):
        self.commands[kwargs["name"]] = kwargs

    def register_skill(self, name, path, description=""):
        assert Path(path).exists()
        self.skills[name] = {"path": Path(path), "description": description}


class PythonFakeLLM:
    def __init__(self):
        self.calls = []

    def complete(self, messages, **kwargs):
        purpose = kwargs.get("purpose", "")
        self.calls.append({"purpose": purpose, "messages": messages, "kwargs": kwargs})
        if purpose.endswith(".python_finalization"):
            assert "<Stdout>" in messages[-1]["content"]
            assert "42" in messages[-1]["content"]
            return TextResult("finalized with execution evidence")
        return TextResult("I will verify this.\n\n```python\nx = 40\nprint(x + 2)\n```")


class TimeoutRecordingLLM(FakeLLM):
    def __init__(self):
        super().__init__()
        self.text_kwargs = []
        self.structured_kwargs = []

    def complete(self, messages, **kwargs):
        self.text_kwargs.append(dict(kwargs))
        return super().complete(messages, **kwargs)

    def complete_structured(self, *, instructions, input, json_schema=None, json_mode=False, schema_name=None, system_prompt=None, **kwargs):
        self.structured_kwargs.append(dict(kwargs))
        return super().complete_structured(
            instructions=instructions,
            input=input,
            json_schema=json_schema,
            json_mode=json_mode,
            schema_name=schema_name,
            system_prompt=system_prompt,
            **kwargs,
        )


class TimeoutThenSuccessLLM:
    def __init__(self):
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append(dict(kwargs))
        if len(self.calls) == 1:
            raise TimeoutError("model request timed out")
        return TextResult("ok")


class SlowFakeLLM(FakeLLM):
    def complete(self, messages, **kwargs):
        time.sleep(0.03)
        return super().complete(messages, **kwargs)

    def complete_structured(self, *, instructions, input, json_schema=None, json_mode=False, schema_name=None, system_prompt=None, **kwargs):
        time.sleep(0.03)
        return super().complete_structured(
            instructions=instructions,
            input=input,
            json_schema=json_schema,
            json_mode=json_mode,
            schema_name=schema_name,
            system_prompt=system_prompt,
            **kwargs,
        )


def test_plugin_registration_and_schemas(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    ctx = FakeCtx()
    register(ctx)

    assert set(ctx.tools) == {"icr_run", "icr_start", "icr_status", "icr_export", "icr_list_runs"}
    assert "icr" in ctx.commands
    assert set(ctx.skills) == {
        "icr-runner",
        "icr-deepthink",
        "icr-contextual-refinement",
        "icr-agentic-refinement",
        "icr-results-review",
        "icr-prompt-parity",
        "icr-state-machine",
    }
    schema = icr_run_schema()
    assert schema["parameters"]["properties"]["mode"]["enum"] == [
        "deepthink",
        "evolving_deepthink",
        "adaptive_deepthink",
        "contextual_refinement",
        "agentic_refinement",
        "dca",
    ]
    config_schema = schema["parameters"]["properties"]["config"]
    assert config_schema["properties"]["max_api_attempts"]["const"] == 4
    assert config_schema["properties"]["python_execution_roles"]["oneOf"][0]["type"] == "string"
    assert config_schema["properties"]["model_call_timeout_kwarg"]["enum"] == ["timeout_seconds", "timeout", "request_timeout", "read_timeout"]
    start_schema = icr_start_schema()
    assert start_schema["name"] == "icr_start"
    assert start_schema["parameters"]["properties"]["mode"]["enum"] == schema["parameters"]["properties"]["mode"]["enum"]


def test_version_metadata_is_consistent(tmp_path):
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    plugin_yaml = (root / "plugin.yaml").read_text(encoding="utf-8")

    assert __version__ == PLUGIN_VERSION
    assert f'version = "{PLUGIN_VERSION}"' in pyproject
    assert f"version: {PLUGIN_VERSION}" in plugin_yaml
    assert "  - icr_start" in plugin_yaml

    record = ICRRunner(FakeLLM(), RunStore(tmp_path / "runs")).run(
        {
            "mode": "dca",
            "challenge": "Version metadata",
            "config": {"retry_delays_seconds": [0, 0, 0], "dca_pool_limit": 1},
        }
    )
    assert record["artifacts"]["state_machine"]["versioned_state"]["_appVersion"] == f"{PLUGIN_NAME}/{PLUGIN_VERSION}"


def test_pip_entry_point_targets_plugin_module():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    entry = 'hermes-iterative-contextual-refinements = "hermes_iterative_contextual_refinements"'

    assert entry in pyproject
    module = importlib.import_module("hermes_iterative_contextual_refinements")
    assert callable(module.register)


def test_source_prompt_resources_are_exact_copies():
    source_dir = Path(__file__).resolve().parents[1] / "hermes_iterative_contextual_refinements" / "source_prompts"
    for name, expected in SOURCE_PROMPT_SHA256.items():
        digest = hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
        assert digest == expected


def test_engines_use_source_system_prompts():
    deepthink = load_deepthink_prompts()
    assert prompt_module.system_prompt("initial_strategy") == deepthink["sys_deepthink_initialStrategy"]
    assert "Do not treat this document as mythology" in prompt_module.system_prompt("initial_strategy")
    assert "80:20 exploration rule" in prompt_module.system_prompt("initial_strategy")
    assert len(prompt_module.system_prompt("hypothesis_generation")) > 60000

    assert contextual_module.MAIN_GENERATOR_PROMPT.startswith("You are the Main Generator and self-corrector")
    assert "Radical Open-Mindedness Protocol" in contextual_module.MAIN_GENERATOR_PROMPT
    assert agentic_module.AGENTIC_SYSTEM_PROMPT.startswith("You are an autonomous refinement agent")
    assert "Run `verify_current_content` on the latest draft before using `Exit`." in agentic_module.AGENTIC_SYSTEM_PROMPT
    adaptive = load_adaptive_prompts()
    assert adaptive_module.ADAPTIVE_ORCHESTRATOR_PROMPT == adaptive["main"]
    assert "You are an Adaptive Deepthink Orchestrator Agent" in adaptive_module.ADAPTIVE_ORCHESTRATOR_PROMPT
    assert adaptive["strategy_generation"] == deepthink["sys_deepthink_initialStrategy"]
    assert dca_module.POOL_GENERATOR_PROMPT.startswith("You are a strategic solution pool generator")
    assert "GENUINE ORTHOGONALITY" in dca_module.POOL_GENERATOR_PROMPT


def test_prompt_builders_preserve_source_runtime_wording():
    strategy_prompt = prompt_module.strategy_generation_prompt("Task", 3)
    assert "genuinely novel, fundamentally distinct" in strategy_prompt
    assert "Return only JSON" in strategy_prompt

    execution_prompt = prompt_module.execution_prompt(
        "Task",
        {"id": "main1", "main_strategy_id": "main1", "main_strategy_text": "Strategy", "sub_strategy_text": "Sub"},
        [{"id": "main1", "text": "Strategy"}, {"id": "main2", "text": "Other"}],
        "<Packet />",
    )
    assert "Context From Other Strategies" in execution_prompt
    assert "Execute the assigned framework completely and faithfully" in execution_prompt
    assert "Relevant Context For Your Current Strategy" in execution_prompt


def test_installed_prompt_parity_validator_passes():
    report = validate_prompt_parity()
    assert report["ok"] is True
    assert report["checked_resources"] == sorted(SOURCE_PROMPT_SHA256)


def test_single_pass_deepthink_flow(tmp_path):
    record = ICRRunner(FakeLLM(), RunStore(tmp_path)).run(
        {
            "mode": "deepthink",
            "challenge": "Solve carefully",
            "config": {
                "main_strategies": 2,
                "sub_strategies": 2,
                "hypotheses": 1,
                "critique_synthesis": True,
                "full_solution_context": True,
                "retry_delays_seconds": [0, 0, 0],
            },
        }
    )
    assert record["status"] == "completed"
    assert len(record["artifacts"]["strategies"]) == 2
    assert len(record["artifacts"]["branches"]) == 4
    final_input = record["artifacts"]["final"]["final_judge_input"]
    assert "<SOLUTION_1>" in final_input
    assert "<SOLUTION_4>" in final_input
    assert "Critique for" not in final_input
    assert all(call["status"] == "completed" for call in record["llm_calls"])
    machine = record["artifacts"]["state_machine"]
    assert machine["upstream_mode"] == "deepthink"
    assert machine["mode_state"]["pipeline"]["finalJudgingStatus"] == "completed"
    assert machine["versioned_state"]["data"]["currentMode"] == "deepthink"
    assert set(machine["indexes"]["branchIds"]) == {"main1-sub1", "main1-sub2", "main2-sub1", "main2-sub2"}
    assert machine["indexes"]["llmCallsByRole"]["final_judge"]


def test_evolving_dfs_replacement_and_heartbeat(tmp_path):
    record = ICRRunner(FakeLLM(), RunStore(tmp_path)).run(
        {
            "mode": "evolving_deepthink",
            "challenge": "Explore branches",
            "config": {
                "main_strategies": 2,
                "hypotheses": 1,
                "evolving_depth": 6,
                "retry_delays_seconds": [0, 0, 0],
            },
        }
    )
    artifacts = record["artifacts"]
    main1 = next(branch for branch in artifacts["active_branches"] if branch["id"] == "main1")
    assert main1["branch_version"] == 2
    assert main1["main_strategy_text"] == "Replacement strategy for main1"
    assert main1["last_hypothesis_flush_global_iteration"] == 5
    assert len(artifacts["replacement_archive"]) == 1
    assert artifacts["replacement_archive"][0]["previous_branch_version"] == 1
    assert [round_["global_iteration"] for round_ in artifacts["hypothesis_rounds"]] == [0, 2, 4, 6]
    assert artifacts["hypothesis_rounds"][-1]["updated_strategy_ids"] == ["main1"]
    assert "persistent strategic failure" in artifacts["replacement_archive"][0]["pqf_reasoning"]
    machine = artifacts["state_machine"]
    assert machine["mode_state"]["pipeline"]["deepthinkVariant"] == "evolving_dfs"
    assert machine["mode_state"]["pipeline"]["hypothesisRounds"][0]["globalIteration"] == 0
    assert machine["mode_state"]["pipeline"]["initialStrategies"][0]["replacementHistory"]


def test_adaptive_deepthink_tool_flow(tmp_path):
    record = ICRRunner(FakeLLM(), RunStore(tmp_path)).run(
        {
            "mode": "adaptive_deepthink",
            "challenge": "Adaptive solve",
            "config": {"hypotheses": 1, "retry_delays_seconds": [0, 0, 0]},
        }
    )
    state = record["artifacts"]["adaptive_state"]
    assert state["selected_solution"].startswith("SELECTED")
    assert [event["tool"] for event in state["tool_events"]] == [
        "GenerateStrategies",
        "GenerateHypotheses",
        "TestHypotheses",
        "ExecuteStrategies",
        "SolutionCritique",
        "CorrectedSolutions",
        "SelectBestSolution",
        "Exit",
    ]
    machine = record["artifacts"]["state_machine"]
    assert machine["upstream_mode"] == "adaptive-deepthink"
    assert machine["graph"]["nodes"] == ["agent", "tools"]
    assert machine["graph"]["shouldExit"] is True
    assert machine["mode_state"]["graphState"]["coreState"]["selectedSolution"].startswith("SELECTED")


class PrematureAdaptiveExitLLM(FakeLLM):
    def _parsed_for(self, purpose: str, prompt: str) -> dict:
        if purpose == "adaptive_deepthink.orchestrator":
            self.adaptive_turn += 1
            plan = [
                {"name": "Exit", "arguments": {}},
                {"name": "GenerateStrategies", "arguments": {"numStrategies": 1}},
                {"name": "GenerateHypotheses", "arguments": {"numHypotheses": 1}},
                {"name": "TestHypotheses", "arguments": {"hypothesisIds": ["hypothesis-1"]}},
                {"name": "ExecuteStrategies", "arguments": {"executions": [{"strategyId": "strategy-1", "hypothesisIds": ["hypothesis-1"]}]}},
                {"name": "SolutionCritique", "arguments": {"executionIds": ["execution-strategy-1"]}},
                {"name": "CorrectedSolutions", "arguments": {"executionIds": ["execution-strategy-1"]}},
                {"name": "SelectBestSolution", "arguments": {"solutionIds": ["execution-strategy-1:Corrected"]}},
                {"name": "Exit", "arguments": {}},
            ]
            return {"assistant_text": f"adaptive turn {self.adaptive_turn}", "tool_calls": [plan[self.adaptive_turn - 1]]}
        return super()._parsed_for(purpose, prompt)


def test_adaptive_rejected_exit_does_not_complete_run(tmp_path):
    record = ICRRunner(PrematureAdaptiveExitLLM(), RunStore(tmp_path)).run(
        {
            "mode": "adaptive_deepthink",
            "challenge": "Adaptive solve",
            "config": {"hypotheses": 1, "retry_delays_seconds": [0, 0, 0], "adaptive_max_tool_turns": 12},
        }
    )
    events = record["artifacts"]["adaptive_state"]["tool_events"]
    assert events[0]["tool"] == "Exit"
    assert events[0]["result"].startswith("[ERROR: Exit rejected")
    assert events[-1]["tool"] == "Exit"
    assert record["artifacts"]["adaptive_state"]["should_exit"] is True
    machine = record["artifacts"]["state_machine"]
    assert machine["transition_log"][-1]["node"] == "END"
    assert machine["indexes"]["toolCallsByTool"]["Exit"] == [1, 9]


def test_contextual_loop_and_condensation(tmp_path):
    record = ICRRunner(FakeLLM(), RunStore(tmp_path)).run(
        {
            "mode": "contextual_refinement",
            "challenge": "Draft something",
            "config": {
                "contextual_iterations": 2,
                "contextual_condensation_interval": 2,
                "retry_delays_seconds": [0, 0, 0],
            },
        }
    )
    state = record["artifacts"]["contextual_state"]
    assert state["iteration_count"] == 2
    assert state["is_running"] is False
    assert len(state["memory_snapshots"]) == 1
    assert {"main_generator", "iterative_agent", "strategic_pool_agent", "memory_agent"} <= {m["role"] for m in state["messages"]}
    machine = record["artifacts"]["state_machine"]
    assert machine["upstream_mode"] == "contextual"
    assert machine["mode_state"]["iterationCount"] == 2
    assert machine["mode_state"]["isRunning"] is False


def test_agentic_edit_verify_exit_loop(tmp_path):
    record = ICRRunner(FakeLLM(), RunStore(tmp_path)).run(
        {
            "mode": "agentic_refinement",
            "content": "bad draft",
            "instruction": "Improve wording.",
            "config": {"retry_delays_seconds": [0, 0, 0]},
        }
    )
    state = record["artifacts"]["agentic_state"]
    assert state["is_complete"] is True
    assert state["current_content"] == "good draft"
    assert state["verification_count"] == 1
    assert state["last_verified_content"] == "good draft"
    assert [event["tool"] for event in state["tool_events"]] == ["read_current_content", "multi_edit", "verify_current_content", "Exit"]
    machine = record["artifacts"]["state_machine"]
    assert machine["upstream_mode"] == "agentic"
    assert machine["graph"]["shouldExit"] is True
    assert machine["mode_state"]["graphState"]["shouldExit"] is True
    assert machine["mode_state"]["graphState"]["currentContent"] == "good draft"


def test_status_export_and_list_handlers(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    ctx = FakeCtx(FakeLLM())
    handlers = make_handlers(ctx)
    run_response = json.loads(
        handlers["icr_run"](
            {
                "mode": "dca",
                "challenge": "Generate alternatives",
                "config": {"retry_delays_seconds": [0, 0, 0], "dca_pool_limit": 2},
            }
        )
    )
    assert run_response["success"] is True
    run_id = run_response["run_id"]
    assert "final" not in run_response
    assert run_response["final_available"] is True
    assert run_response["progress"]["current"]["stage"] == "handler"
    assert run_response["progress"]["event_count"] >= len(run_response["progress"]["recent_events"])
    assert run_response["export_hint"]["args"]["run_id"] == run_id
    assert run_response["checkpoint_count"] > 0
    assert run_response["last_checkpoint"]["stage"] == "runner"

    status = json.loads(handlers["icr_status"]({"run_id": run_id}))
    assert status["status"] == "completed"
    assert status["llm_call_count"] == 3
    assert "state_machine" in status["artifact_keys"]
    assert status["progress"]["current"]["stage"] == "runner"
    assert status["progress"]["current"]["status"] == "completed"
    assert status["progress"]["event_count"] >= len(status["progress"]["recent_events"])
    assert status["active_llm_calls"] == []
    assert status["final_available"] is True
    assert status["checkpoint_count"] > 0
    assert status["resume_metadata"]["node_level_resume_supported"] is False

    exported = json.loads(handlers["icr_export"]({"run_id": run_id, "format": "markdown"}))
    assert exported["format"] == "markdown"
    assert f"# ICR Run {run_id}" in exported["content"]

    listed = json.loads(handlers["icr_list_runs"]({"limit": 5}))
    assert [row["run_id"] for row in listed["runs"]] == [run_id]
    assert listed["runs"][0]["artifact_keys"]
    raw_run = json.loads(Path(run_response["path"]).read_text(encoding="utf-8"))
    assert raw_run["artifacts"] == {}
    assert raw_run["artifact_keys"]
    artifact_ref = raw_run["blob_refs"]["artifacts"]
    assert (tmp_path / ".hermes" / "icr" / artifact_ref).exists()
    loaded = RunStore().load(run_id)
    assert "final" in loaded["artifacts"]
    assert not list((tmp_path / ".hermes" / "icr" / "runs").glob("*.tmp"))


def test_icr_start_runs_in_background_and_can_be_polled(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    ctx = FakeCtx(SlowFakeLLM())
    handlers = make_handlers(ctx)
    started_at = time.monotonic()
    started = json.loads(
        handlers["icr_start"](
            {
                "mode": "dca",
                "challenge": "Generate alternatives",
                "config": {"retry_delays_seconds": [0, 0, 0], "dca_pool_limit": 2},
            }
        )
    )

    assert started["success"] is True
    assert time.monotonic() - started_at < 0.1
    run_id = started["run_id"]
    assert started["status"] in {"queued", "processing", "completed"}
    assert started["background"]["process_local"] is True
    assert started["status_hint"]["args"]["run_id"] == run_id

    deadline = time.monotonic() + 3
    status = {}
    while time.monotonic() < deadline:
        status = json.loads(handlers["icr_status"]({"run_id": run_id}))
        if status["status"] == "completed":
            break
        time.sleep(0.02)

    assert status["status"] == "completed"
    assert status["final_available"] is True
    assert status["checkpoint_count"] > 0
    assert status["background"]["status"] == "completed"
    exported = json.loads(handlers["icr_export"]({"run_id": run_id, "format": "markdown"}))
    assert f"# ICR Run {run_id}" in exported["content"]


def test_activity_heartbeat_pings_during_synchronous_work(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(heartbeat_module, "current_activity_callback", lambda: events.append)

    with heartbeat_module.ActivityHeartbeat("ICR run unit", interval_seconds=0.01):
        deadline = time.monotonic() + 0.2
        while not any(": running" in event for event in events) and time.monotonic() < deadline:
            time.sleep(0.01)

    assert any(": started" in event for event in events)
    assert any(": running" in event for event in events)
    assert any(": completed" in event for event in events)


def test_activity_heartbeat_can_stop_on_stale_progress():
    events: list[str] = []

    with heartbeat_module.ActivityHeartbeat(
        "ICR run stale-unit",
        callback=events.append,
        interval_seconds=0.01,
        stale_after_seconds=0.02,
    ):
        deadline = time.monotonic() + 0.3
        while not any("stale; heartbeat stopped" in event for event in events) and time.monotonic() < deadline:
            time.sleep(0.01)

    assert any("stale; heartbeat stopped" in event for event in events)


def test_llm_call_progress_is_persisted_before_provider_returns(tmp_path):
    store = RunStore(tmp_path / "runs")
    cfg = build_config({"retry_delays_seconds": [0, 0, 0]}, mode="deepthink")
    record = new_run("deepthink", {"challenge": "observe progress"}, cfg.as_dict(), run_id="progress-run")
    store.save(record)
    snapshots = []

    class InspectingLLM:
        def complete(self, messages, **kwargs):
            snapshots.append(store.load("progress-run"))
            return TextResult("ok")

    progress = RunProgress(record, store, cfg)
    llm = ICRLlm(InspectingLLM(), record, cfg, progress=progress)
    try:
        assert llm.complete(role="solution_attempt", purpose="unit.progress", prompt="hello") == "ok"
    finally:
        llm.close()

    before_return = snapshots[0]
    active_call = before_return["llm_calls"][0]
    assert active_call["status"] == "processing"
    assert active_call["attempts"][0]["status"] == "processing"
    assert before_return["progress"]["current"]["status"] == "attempt_started"

    completed = store.load("progress-run")
    assert completed["llm_calls"][0]["status"] == "completed"
    assert completed["progress"]["current"]["status"] == "completed"


def test_multi_edit_operations_are_sequential():
    content = "alpha beta"
    first = apply_operation(content, {"action": "insert_after", "target": "alpha", "content": " gamma"})
    second = apply_operation(first["result"], {"action": "search_and_replace", "target": "gamma beta", "content": "delta"})
    assert first["success"] is True
    assert second["success"] is True
    assert second["result"] == "alpha delta"


def test_config_string_values_are_parsed_without_silent_truthiness():
    cfg = build_config(
        {
            "refinement": "false",
            "python_execution_enabled": "true",
            "python_execution_roles": "solution_attempt,self_improvement",
            "retry_delays_seconds": [0, 0, 0],
            "contextual_retry_delays_seconds": [0, 0],
        },
        mode="deepthink",
    )

    assert cfg.refinement is False
    assert cfg.python_execution_enabled is True
    assert cfg.python_execution_roles == ("solution_attempt", "self_improvement")
    timeout_cfg = build_config(
        {
            "model_call_timeout_seconds": "900",
            "model_call_timeout_retry_seconds": "1800",
            "model_call_timeout_kwarg": "request_timeout",
            "run_deadline_seconds": "3600",
            "heartbeat_stale_seconds": "900",
        },
        mode="deepthink",
    )
    assert timeout_cfg.model_call_timeout_seconds == 900
    assert timeout_cfg.model_call_timeout_retry_seconds == 1800
    assert timeout_cfg.model_call_timeout_kwarg == "request_timeout"
    assert timeout_cfg.run_deadline_seconds == 3600
    assert timeout_cfg.heartbeat_stale_seconds == 900

    with pytest.raises(ValueError, match="contextual_retry_delays_seconds"):
        build_config({"contextual_retry_delays_seconds": [1]}, mode="contextual_refinement")
    with pytest.raises(ValueError, match="dca_pool_limit"):
        build_config({"dca_pool_limit": 11}, mode="dca")
    with pytest.raises(ValueError, match="model_call_timeout_kwarg"):
        build_config({"model_call_timeout_kwarg": "bad_timeout"}, mode="deepthink")
    with pytest.raises(ValueError, match="run_deadline_seconds"):
        build_config({"run_deadline_seconds": -1}, mode="deepthink")


def test_model_call_timeout_is_passed_to_text_and_structured_calls():
    cfg = build_config(
        {
            "model_call_timeout_seconds": 777,
            "model_call_timeout_kwarg": "timeout_seconds",
            "retry_delays_seconds": [0, 0, 0],
        },
        mode="deepthink",
    )
    record = {"run_id": "timeout-run", "llm_calls": [], "usage": {}, "artifacts": {}}
    fake = TimeoutRecordingLLM()
    llm = ICRLlm(fake, record, cfg)
    try:
        text = llm.complete(role="solution_attempt", purpose="unit.text_timeout", prompt="hello", system_prompt="system")
        parsed = llm.structured(role="initial_strategy", purpose="unit.structured_timeout", instructions="json", prompt="{}", schema=None)
    finally:
        llm.close()

    assert text == "Text response for unit.text_timeout."
    assert parsed == {}
    assert fake.text_kwargs[0]["timeout_seconds"] == 777
    assert fake.structured_kwargs[0]["timeout_seconds"] == 777
    assert record["llm_calls"][0]["attempts"][0]["timeout_seconds"] == 777
    assert record["llm_calls"][1]["attempts"][0]["timeout_kwarg"] == "timeout_seconds"


def test_timeout_retry_applies_longer_timeout_after_host_default_timeout():
    cfg = build_config(
        {
            "retry_delays_seconds": [0, 0, 0],
            "model_call_timeout_retry_seconds": 1234,
        },
        mode="deepthink",
    )
    record = {"run_id": "timeout-retry-run", "llm_calls": [], "usage": {}, "artifacts": {}}
    fake = TimeoutThenSuccessLLM()
    llm = ICRLlm(fake, record, cfg)
    try:
        result = llm.complete(role="solution_attempt", purpose="unit.timeout_retry", prompt="hello", system_prompt="system")
    finally:
        llm.close()

    assert result == "ok"
    assert "timeout_seconds" not in fake.calls[0]
    assert fake.calls[1]["timeout_seconds"] == 1234
    attempts = record["llm_calls"][0]["attempts"]
    assert attempts[0]["is_timeout"] is True
    assert attempts[1]["timeout_seconds"] == 1234
    assert attempts[1]["status"] == "completed"


def test_slash_run_parses_config_and_agentic_content():
    args = parse_icr_args('run deepthink --config-json \'{"hypotheses": 1, "retry_delays_seconds": [0, 0, 0]}\' --run-id custom Solve this')
    assert args["mode"] == "deepthink"
    assert args["run_id"] == "custom"
    assert args["challenge"] == "Solve this"
    assert args["config"]["hypotheses"] == 1

    agentic = parse_icr_args('run agentic_refinement --content "bad draft" --instruction "fix wording"')
    assert agentic["mode"] == "agentic_refinement"
    assert agentic["content"] == "bad draft"
    assert agentic["instruction"] == "fix wording"


def test_python_session_persists_state(tmp_path):
    session = PythonSession(tmp_path / "py", timeout_seconds=2)
    try:
        first = session.execute("x = 41\nprint('ready')")
        second = session.execute("print(x + 1)")
    finally:
        session.close()

    assert first["ok"] is True
    assert first["stdout"] == "ready\n"
    assert second["ok"] is True
    assert second["stdout"] == "42\n"


def test_python_assisted_llm_executes_and_finalizes():
    cfg = build_config(
        {
            "retry_delays_seconds": [0, 0, 0],
            "python_execution_enabled": True,
            "python_execution_timeout_seconds": 2,
            "python_execution_roles": ["solution_attempt"],
            "model_call_timeout_seconds": 654,
        },
        mode="deepthink",
    )
    record = {"run_id": "python-run", "llm_calls": [], "usage": {}, "artifacts": {}}
    fake = PythonFakeLLM()
    llm = ICRLlm(fake, record, cfg)
    try:
        result = llm.complete(
            role="solution_attempt",
            purpose="unit.python_assisted",
            prompt="calculate",
            system_prompt="system",
        )
    finally:
        llm.close()

    assert result == "finalized with execution evidence"
    assert extract_python_blocks(record["llm_calls"][0]["raw_response_before_python"]) == ["x = 40\nprint(x + 2)"]
    assert record["python_executions"][0]["stdout"] == "42\n"
    assert record["llm_calls"][0]["python_executions"][0]["ok"] is True
    assert fake.calls[0]["purpose"] == "unit.python_assisted"
    assert fake.calls[1]["purpose"] == "unit.python_assisted.python_finalization"
    assert fake.calls[0]["kwargs"]["timeout_seconds"] == 654
    assert fake.calls[1]["kwargs"]["timeout_seconds"] == 654
    assert "Python execution is available" in fake.calls[0]["messages"][0]["content"]
