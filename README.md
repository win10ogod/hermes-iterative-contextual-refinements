# Hermes Iterative Contextual Refinements

Hermes plugin for running Iterative Contextual Refinements (ICR) from Hermes Agent without bringing a separate API key. All model calls go through `ctx.llm`, so provider/model overrides follow Hermes' plugin trust gate. Without explicit trust configuration, the plugin uses the host model.

## Capabilities

- `deepthink`: single-pass strategic pipeline with main strategies, optional sub-strategies, hypothesis generation/testing, execution, critique, optional synthesis/full-solution context, correction, and final judge.
- `evolving_deepthink`: Evolving DFS with stable strategy slots, `branchVersion`, branch-local/global iteration, structured solution pools, memory bank, PQF keep/update, replacement archive, hypothesis heartbeat, and final judge that sees only active candidate texts.
- `adaptive_deepthink`: tool-interface orchestration with `GenerateStrategies`, `GenerateHypotheses`, `TestHypotheses`, `ExecuteStrategies`, `SolutionCritique`, `CorrectedSolutions`, `SelectBestSolution`, and `Exit`.
- `contextual_refinement`: main generator, iterative critique agent, strategic pool agent, memory agent, isolated histories, and history condensation.
- `agentic_refinement`: internal tool loop preserving `read_current_content`, `multi_edit`, `verify_current_content`, `searchacademia`, `searchacademia_and`, and verified-only `Exit`.
- `dca`: dynamic compute alternatives with pool generator and local pool evolution.

Same-stage ICR work is executed concurrently where the source design uses parallel agent calls: sub-strategy generation, hypothesis testing, branch execution, critique, correction, Evolving DFS solution pools, memory agents, PQF groups, Adaptive Deepthink batch tools, and DCA local pools.

Python-assisted agent roles are available with explicit config. When enabled, selected roles may return fenced `python` blocks; the plugin executes them in a persistent role-local Python session, records stdout/stderr/errors, then asks the same role to produce the final answer from the execution evidence.

The plugin saves complete run artifacts to:

```text
$HERMES_HOME/icr/runs/<run_id>.json
```

Each run records raw prompts, raw responses, parsed structured data, statuses, errors, retry attempts, usage metadata, semantic mode adjustments, and final exports.

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
- Max model attempts: exactly `4`
- Deepthink retry delays default to `20`, `40`, and `80` seconds
- Evolving DFS forces selective hypothesis routing and PQF, recorded in the run config
- Final judge receives candidate solution texts only, not internal search machinery
- Python execution is off by default and must be enabled through `python_execution_enabled`; execution artifacts are recorded under `python_executions`

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
