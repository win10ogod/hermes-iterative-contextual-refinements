---
name: icr-runner
description: Run ICR modes from Hermes tools, choose configuration safely, inspect saved artifacts, and export results.
---

# ICR Runner

Use this skill when a user wants to run an Iterative Contextual Refinements mode through Hermes.

## Choose The Mode

- Use `deepthink` for a bounded strategic pass with optional critique/correction and final judge.
- Use `evolving_deepthink` when the task benefits from persistent branch evolution, memory, solution pools, PQF branch replacement, and hypothesis heartbeats.
- Use `adaptive_deepthink` when an orchestration agent should decide which Deepthink tools to call and in what order.
- Use `contextual_refinement` for repeated draft generation, critique, strategic pool updates, and memory condensation.
- Use `agentic_refinement` for direct mutation of a working draft with read/edit/verify/search/exit tools.
- Use `dca` for dynamic compute alternatives: broad pool generation followed by local pool evolution.

## Run

Call `icr_run` with:

```json
{
  "mode": "deepthink",
  "challenge": "Core task",
  "config": {
    "main_strategies": 3,
    "hypotheses": 2,
    "refinement": true
  }
}
```

For `agentic_refinement`, use:

```json
{
  "mode": "agentic_refinement",
  "content": "Current draft",
  "instruction": "Refine for correctness, structure, and clarity."
}
```

## Configuration Discipline

Do not lower capability to make a run faster. The plugin validates ICR limits:

- Main strategies: 1-10, or 1-5 in Evolving DFS.
- Hypotheses: 0-6.
- Evolving DFS depth: 1-10.
- Max API attempts: 4.
- Deepthink retry delays default to 20, 40, 80 seconds.

If a faster diagnostic run is needed, explicitly say it is a diagnostic run and keep its config visible in the run artifact.

## Python-Assisted Roles

Use Python execution only when executable verification, calculation, data processing, or generated artifacts materially improve the run. Enable it explicitly:

```json
{
  "config": {
    "python_execution_enabled": true,
    "python_execution_timeout_seconds": 30,
    "python_execution_roles": ["hypothesis_testing", "solution_attempt", "self_improvement"]
  }
}
```

The plugin executes fenced `python` blocks in persistent role-local sessions, records `python_executions`, and asks the role to finalize its answer from stdout, stderr, and error evidence. Sessions are closed at run end.

## Parallel Stages

Same-stage work runs concurrently while preserving artifact order. Expect parallel execution for branch solution attempts, critiques, corrections, hypothesis tests, Evolving DFS solution pools, due memory agents, PQF groups, Adaptive Deepthink batch tools, and DCA local pools.

## Inspect

Use:

- `icr_status` to see status, errors, usage, artifact keys, and call count.
- `icr_export` with `format: "json"` for full evidence.
- `icr_export` with `format: "markdown"` for a compact summary.
- `icr_list_runs` to find recent runs.

Artifacts are saved under `$HERMES_HOME/icr/runs/<run_id>.json`.
