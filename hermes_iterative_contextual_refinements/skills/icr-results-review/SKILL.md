---
name: icr-results-review
description: Review saved ICR runs, verify artifact evidence, inspect final boundaries, and export JSON or Markdown summaries.
---

# ICR Results Review

Use this skill when inspecting or reporting on an ICR run.

## Find Runs

Call:

```json
{"limit": 20}
```

with `icr_list_runs`. Filter by `mode` or `status` when needed.

## Status

Call:

```json
{"run_id": "icr-..."}
```

with `icr_status`. Confirm:

- `status`
- `errors`
- `usage`
- `artifact_keys`
- `llm_call_count`
- `checkpoint_count`
- `last_checkpoint`
- `background` when the run was started with `icr_start`

## Export

Use JSON for evidence:

```json
{"run_id": "icr-...", "format": "json"}
```

Use Markdown for a compact summary:

```json
{"run_id": "icr-...", "format": "markdown"}
```

## Evidence Checklist

When claiming a run completed, verify the saved JSON contains:

- `status: completed`
- `llm_calls` with raw prompts and raw responses
- parsed structured data for structured calls
- usage metadata when the provider returned it
- `artifacts.final`
- `checkpoint_count` and `resume_metadata`
- no unhandled errors
- `python_executions` when Python-assisted roles were enabled, including stdout, stderr, error, role, and code

Completed run indexes may store large artifacts in `$HERMES_HOME/icr/blobs/<run_id>/artifacts.json`. Use `icr_export` or `RunStore.load()` for resolved artifacts instead of reading only the raw run index.

For Deepthink/Evolving DFS, additionally verify:

- final judge input contains candidate solutions only
- replacement archive exists when PQF updated a branch
- branch versions and branch-local iteration reset after replacement
- hypothesis rounds include heartbeat rounds when depth reaches even iterations
- same-stage artifacts are present for all expected branches or hypotheses, even though execution was concurrent

For Agentic Refinement, verify:

- Exit succeeded only after verification of the latest content
- content history shows edits
- verifier reports are preserved
