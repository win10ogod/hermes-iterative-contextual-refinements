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

When `icr_run` is executed inside Hermes gateway, the plugin emits a lightweight activity heartbeat for the duration of the synchronous tool call. This prevents long but active ICR runs from being misclassified as inactive while preserving the same prompts, retry behavior, strategy counts, and state-machine artifacts. Set `HERMES_ICR_ACTIVITY_HEARTBEAT_SECONDS` to tune the heartbeat cadence; the default is `10` seconds. Set `heartbeat_stale_seconds` in run config, or `HERMES_ICR_HEARTBEAT_STALE_SECONDS`, to stop refreshing gateway activity when no real ICR progress has been recorded for that many seconds.

Python-assisted agent roles are available with explicit config. When enabled, selected roles may return fenced `python` blocks; the plugin executes them in a persistent role-local Python session, records stdout/stderr/errors, then asks the same role to produce the final answer from the execution evidence.

The plugin saves complete run artifacts to:

```text
$HERMES_HOME/icr/runs/<run_id>.json
$HERMES_HOME/icr/blobs/<run_id>/artifacts.json
```

Each run records raw prompts, raw responses, parsed structured data, statuses, errors, retry attempts, usage metadata, semantic mode adjustments, durable progress events, checkpoints, active LLM-call state, and final exports.

Completed run indexes keep large artifacts in the blob file above. `icr_status`, `icr_export`, and the Python `RunStore.load()` API resolve those blobs automatically, so callers still see full artifacts while routine polling stays small.

State-machine artifacts are saved in the resolved artifacts blob. They keep the original Hermes artifacts intact while projecting the run into upstream field names such as `activeDeepthinkPipeline`, `activeAgenticState`, `activeContextualState`, `activeAdaptiveDeepthinkState`, `DeepthinkPipelineState`, `AgenticState`, `ContextualState`, `AdaptiveDeepthinkStoreState`, and `DCAPipelineState`.

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

If the active Hermes profile declares an explicit `toolsets:` list, include the plugin toolset too:

```yaml
toolsets:
  - hermes-cli
  - icr
```

When no explicit toolset filter is used, Hermes discovers the plugin-provided `icr` toolset automatically. With an explicit filter, plugin enablement and tool exposure are separate: `plugins.enabled` loads and registers the plugin, while `toolsets` controls whether the model receives `icr_run`, `icr_start`, `icr_status`, `icr_export`, and `icr_list_runs`.

### Pip plugin

```bash
cd /mnt/f/多模態記憶/hermes-iterative-contextual-refinements
python -m pip install -e .
```

The package exposes the entry point group:

```toml
[project.entry-points."hermes_agent.plugins"]
hermes-iterative-contextual-refinements = "hermes_iterative_contextual_refinements"
```

After updating the repository, reinstall the editable package so Python entry-point
metadata is refreshed:

```bash
python -m pip install -U -e .
```

If Hermes reports the plugin as enabled but the model does not see `icr_*` tools,
enable the plugin toolset for the active platform:

```bash
hermes tools enable icr --platform cli
```

Inside an active Hermes CLI session, the same fix is:

```text
/tools enable icr
```

Run the registration doctor when the cause is unclear:

```bash
icr-hermes-doctor --platform cli
```

or, if the slash command is available:

```text
/icr doctor --platform cli
```

The doctor checks the installed package version, Hermes entry point, plugin
discovery result, registry state, active platform toolsets, and final
model-facing tool definitions. A common disabled-toolset signature is
`known_plugin_toolsets.cli` containing `icr` while `platform_toolsets.cli` does
not.

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

`icr_run` intentionally returns a compact completion payload: `run_id`, `status`, artifact path, compact progress, active LLM calls, and an `export_hint`. It does not embed the full final artifact in the tool response, so completed runs do not stall while returning a very large result. Use `icr_export` to retrieve the full JSON or Markdown output.

### `icr_start`

```json
{
  "mode": "dca",
  "challenge": "Generate alternatives for ...",
  "config": {
      "model_call_timeout_seconds": 900,
      "run_deadline_seconds": 7200,
      "heartbeat_stale_seconds": 1800
  }
}
```

`icr_start` starts the same ICR runner in a process-local background thread and returns immediately with `run_id`, `path`, compact progress, and polling/export hints. Use it when a synchronous tool response might hit a gateway response timeout even though the model calls are still progressing. Poll with `icr_status` and retrieve the final result with `icr_export`.

Background execution is process-local: if the Hermes plugin process exits, the in-memory worker thread exits too. The saved run file still contains request/config/progress/checkpoint metadata for diagnosis and restart planning.

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
/icr start deepthink Analyze this design...
/icr run evolving_deepthink --config-json '{"main_strategies":3,"hypotheses":2,"evolving_depth":6}' Analyze this design...
/icr run agentic_refinement --content "Current draft" --instruction "Improve correctness and structure."
/icr doctor --platform cli
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
- Whole-run deadline is explicit: omit `run_deadline_seconds` or set `0` to keep full-run execution unlimited; set a positive value to fail at the next ICR progress boundary after that deadline.
- Heartbeat stale cutoff is explicit: omit `heartbeat_stale_seconds` or set `0` to keep heartbeat refreshes unlimited; set a positive value to stop heartbeat refreshes when no LLM/stage progress is recorded.
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

For diagnosing suspected stalls, use explicit progress controls instead of reducing ICR capability:

```json
{
  "config": {
    "model_call_timeout_seconds": 900,
    "run_deadline_seconds": 7200,
    "heartbeat_stale_seconds": 1800
  }
}
```

`icr_status` returns the durable `progress` object, `active_llm_calls`, background metadata, and the latest checkpoint, so a running artifact can show whether the plugin is preparing a model call, waiting on a specific role/purpose, attaching the state machine, serializing the final tool response, or continuing in a process-local background worker.

The `progress` object returned by `icr_run`, `icr_start`, and `icr_status` is compact: current progress, event count, recent events, checkpoint count, and latest checkpoint. The complete event and checkpoint logs remain in the JSON export.

Checkpoints are diagnostic metadata captured at observable runner and LLM boundaries. They identify the latest durable stage, LLM call count, and artifact keys. They do not claim arbitrary LangGraph node-level resume yet; `resume_metadata.node_level_resume_supported` is intentionally `false` until exact node replay is implemented and tested.

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
