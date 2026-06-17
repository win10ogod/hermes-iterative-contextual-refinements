# Hermes Iterative Contextual Refinements

Hermes plugin for running Iterative Contextual Refinements (ICR) from Hermes Agent without bringing a separate API key. All model calls go through `ctx.llm`, so provider/model overrides follow Hermes' plugin trust gate. Without explicit trust configuration, the plugin uses the host model.

## Capabilities

- `deepthink`: single-pass strategic pipeline with main strategies, optional sub-strategies, hypothesis generation/testing, execution, critique, optional synthesis/full-solution context, correction, and final judge.
- `evolving_deepthink`: Evolving DFS with stable strategy slots, `branchVersion`, branch-local/global iteration, structured solution pools, memory bank, PQF keep/update, replacement archive, hypothesis heartbeat, and final judge that sees only active candidate texts.
- `adaptive_deepthink`: tool-interface orchestration with `GenerateStrategies`, `GenerateHypotheses`, `TestHypotheses`, `ExecuteStrategies`, `SolutionCritique`, `CorrectedSolutions`, `SelectBestSolution`, and `Exit`.
- `contextual_refinement`: main generator, iterative critique agent, strategic pool agent, memory agent, isolated histories, and history condensation.
- `agentic_refinement`: internal tool loop preserving `read_current_content`, `multi_edit`, `verify_current_content`, `searchacademia`, `searchacademia_and`, and verified-only `Exit`.
- `dca`: dynamic compute alternatives with pool generator and local pool evolution.

Each run also emits `artifacts.state_machine`, an upstream-shaped React/LangGraph state snapshot. It includes a `VersionedState`-compatible export wrapper, legacy `ExportedConfig` fields, the active `ModeStateHandler` state, LangGraph node/edge/reducer metadata for Agentic and Adaptive Deepthink, pipeline transition logs, restore/sanitizer plans, and optimized indexes for roles, purposes, branches, hypotheses, tools, final candidates, messages, and content versions.

Default role system prompts are loaded from copied upstream prompt resources in `hermes_iterative_contextual_refinements/source_prompts/`. The package records SHA-256 checksums for those resources and tests that engines use the extracted upstream prompts instead of shortened reimplementations.

Prompt parity can be checked after installation with:

```bash
python -m hermes_iterative_contextual_refinements.prompt_parity
```

Same-stage ICR work is executed concurrently where the source design uses parallel agent calls: sub-strategy generation, hypothesis testing, branch execution, critique, correction, Evolving DFS solution pools, memory agents, PQF groups, Adaptive Deepthink batch tools, and DCA local pools.

When `icr_run` is executed inside Hermes gateway, the plugin emits a lightweight activity heartbeat for the duration of the synchronous tool call. This prevents long but active ICR runs from being misclassified as inactive while preserving the same prompts, retry behavior, strategy counts, and state-machine artifacts. Set `HERMES_ICR_ACTIVITY_HEARTBEAT_SECONDS` to tune the heartbeat cadence; the default is `10` seconds.

Python-assisted agent roles are available with explicit config. When enabled, selected roles may return fenced `python` blocks; the plugin executes them in a persistent role-local Python session, records stdout/stderr/errors, then asks the same role to produce the final answer from the execution evidence.

The plugin saves complete run artifacts to:

```text
$HERMES_HOME/icr/runs/<run_id>.json
```

Each run records raw prompts, raw responses, parsed structured data, statuses, errors, retry attempts, usage metadata, semantic mode adjustments, and final exports.

State-machine artifacts are saved inside the same run JSON. They keep the original Hermes artifacts intact while projecting the run into upstream field names such as `activeDeepthinkPipeline`, `activeAgenticState`, `activeContextualState`, `activeAdaptiveDeepthinkState`, `DeepthinkPipelineState`, `AgenticState`, `ContextualState`, `AdaptiveDeepthinkStoreState`, and `DCAPipelineState`.

## Install

### Directory plugin

Copy or symlink this repository into one of Hermes' plugin locations, for example:

```bash
mkdir -p "$HERMES_HOME/plugins"
ln -s /mnt/f/多模態記憶/hermes-iterative-contextual-refinements "$HERMES_HOME/plugins/hermes-iterative-contextual-refinements"
```

Enable it in Hermes config:

```yaml
plugins:
  enabled:
    - hermes-iterative-contextual-refinements
```

### Pip plugin

```bash
cd /mnt/f/多模態記憶/hermes-iterative-contextual-refinements
python -m pip install -e .
```

The package exposes the entry point group:

```toml
[project.entry-points."hermes_agent.plugins"]
hermes-iterative-contextual-refinements = "hermes_iterative_contextual_refinements:register"
```

## Tools

### `icr_run`

```json
{
  "mode": "evolving_deepthink",
  "challenge": "Design a robust migration plan for ...",
  "config": {
      "main_strategies": 3,
      "hypotheses": 2,
      "evolving_depth": 6,
      "model_call_timeout_seconds": 900,
      "model_call_timeout_retry_seconds": 1800,
      "python_execution_enabled": true,
      "python_execution_roles": ["hypothesis_testing", "solution_attempt", "self_improvement"],
      "retry_delays_seconds": [20, 40, 80]
  }
}
```

For `agentic_refinement`, pass `content` and optional `instruction` instead of `challenge`.

### `icr_status`

```json
{"run_id": "icr-abc123"}
```

### `icr_export`

```json
{"run_id": "icr-abc123", "format": "markdown"}
```

### `icr_list_runs`

```json
{"limit": 20, "mode": "deepthink"}
```

## Slash Command

`/icr` supports a compact CLI-style form:

```text
/icr list 10
/icr list 20 completed deepthink
/icr status icr-abc123
/icr export icr-abc123 markdown
/icr export icr-abc123 markdown /tmp/icr-abc123.md
/icr run deepthink Analyze this design...
/icr run evolving_deepthink --config-json '{"main_strategies":3,"hypotheses":2,"evolving_depth":6}' Analyze this design...
/icr run agentic_refinement --content "Current draft" --instruction "Improve correctness and structure."
```

Use `icr_run` for detailed config.

## Limits Preserved

The plugin rejects invalid user configuration instead of silently reducing the run:

- Deepthink main strategies: `1-10`
- Evolving DFS main strategies: `1-5`
- Sub-strategies: `0`, `2`, `3`, `4`, or `5`; forced to `0` in Evolving DFS and recorded as a semantic adjustment
- Hypotheses: `0-6`
- Evolving DFS depth: `1-10`
- DCA pool limit: `1-10`
- Max model attempts: exactly `4`
- Deepthink retry delays default to `20`, `40`, and `80` seconds
- Main model call timeout override is explicit: omit `model_call_timeout_seconds` or set `0` to keep the Hermes host default; set a positive value to pass a timeout to `ctx.llm`.
- After a timeout error, retries use `model_call_timeout_retry_seconds` (default `1200`) so long ICR prompts can recover from shorter host/provider defaults.
- Evolving DFS forces selective hypothesis routing and PQF, recorded in the run config
- Evolving DFS records the first hypothesis round at upstream `global_iteration: 0` and initial branch execution at global iteration `1`
- Final judge receives candidate solution texts only, not internal search machinery
- Python execution is off by default and must be enabled through `python_execution_enabled`; execution artifacts are recorded under `python_executions`

## State Machine Parity

Use the `icr-state-machine` skill or inspect `artifacts.state_machine` directly. Important fields:

- `versioned_state`: upstream `StateVersion.ts`-style wrapper.
- `exported_config`: legacy export fields for older import tooling.
- `mode_state`: active handler state for the run's upstream mode.
- `graph`: React pipeline or LangGraph node/edge/reducer description.
- `transition_log`: ordered state creation, model calls, tool calls/results, events, and terminal state.
- `indexes`: direct replay/audit lookups, an optimization beyond the browser runtime.

Adaptive Deepthink now rejects premature `Exit` and continues orchestration until `SelectBestSolution` has populated `selected_solution`. Rejected Exit attempts remain visible in `adaptive_state.tool_events` and `state_machine.transition_log`.

## Python-Assisted Roles

Enable Python only for roles that need executable verification or computation:

```json
{
  "config": {
    "python_execution_enabled": true,
    "python_execution_timeout_seconds": 30,
    "python_execution_roles": [
      "hypothesis_testing",
      "solution_attempt",
      "solution_critique",
      "self_improvement"
    ]
  }
}
```

Each role gets an isolated persistent session for the run, so variables created by one `solution_attempt` Python block remain available to later `solution_attempt` blocks in the same run, but not to other roles. Sessions are closed when the run finishes.

## Main Model Timeouts

ICR prompts can be large, especially with full upstream Deepthink prompts and hypothesis packets. If the host model call times out, configure the main model request timeout instead of reducing strategy counts or prompt content:

```json
{
  "config": {
    "model_call_timeout_seconds": 900,
    "model_call_timeout_retry_seconds": 1800,
    "model_call_timeout_kwarg": "timeout_seconds"
  }
}
```

`model_call_timeout_seconds` is passed from the first attempt. If it is omitted, the first attempt keeps the Hermes host default; if that attempt fails with a timeout, later retries pass `model_call_timeout_retry_seconds`. Supported timeout keyword names are `timeout_seconds`, `timeout`, `request_timeout`, and `read_timeout`; choose the one your Hermes LLM provider accepts.

This is separate from Hermes gateway inactivity protection. The plugin heartbeat keeps the gateway activity clock fresh while a long `icr_run` is still working. If the gateway timeout is still reached, set `agent.gateway_timeout` above the expected full ICR runtime or use `0` to disable the gateway limit.

## Role Model Overrides

Per-role provider/model overrides are passed through `ctx.llm`:

```json
{
  "config": {
    "role_overrides": {
      "final_judge": {"provider": "openrouter", "model": "openai/gpt-4o"},
      "solution_attempt": {"model": "anthropic/claude-sonnet-4"}
    }
  }
}
```

Hermes enforces trust. If the plugin is not authorized for an override, `ctx.llm` raises the host trust error.

## Tests

The test suite uses a fake deterministic LLM and does not call real model APIs.

```bash
cd /mnt/f/多模態記憶/hermes-iterative-contextual-refinements
python -m pytest
```
