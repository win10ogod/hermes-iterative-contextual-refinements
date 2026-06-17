---
name: icr-agentic-refinement
description: Operate agentic refinement with read_current_content, multi_edit, verify_current_content, academia search tools, and verified-only Exit.
---

# ICR Agentic Refinement

Use `agentic_refinement` when a mutable draft should be improved through tool calls.

## Required Inputs

```json
{
  "mode": "agentic_refinement",
  "content": "Initial draft",
  "instruction": "Refine for correctness and clarity."
}
```

## Tool Semantics

The internal loop supports:

- `read_current_content`: read full draft or a 1-indexed line range.
- `multi_edit`: apply sequential operations. Later operations see earlier successful edits.
- `verify_current_content`: run an independent verifier on the current draft.
- `searchacademia`: query arXiv for a single query.
- `searchacademia_and`: query arXiv for entries matching all terms.
- `Exit`: finish only if the current draft is exactly the last verified draft.

## Edit Operations

`multi_edit.operations` entries use:

- `search_and_replace` with `target` and `content`.
- `delete` with `target`.
- `insert_before` with `target` and `content`.
- `insert_after` with `target` and `content`.

Each operation reports success or failure. A failed operation does not stop later operations; it leaves the current draft unchanged for that operation.

## Verification Gate

If the agent edits after verification, `last_verified_content` is cleared. `Exit` must reject until `verify_current_content` runs again on the latest draft.

## Review Checklist

Check:

- `agentic_state.content_history` records content after successful edits.
- `agentic_state.verification_count` increases after verification.
- `agentic_state.last_verified_content` equals `current_content` before successful Exit.
- Rejected Exit attempts are visible in `tool_events`.

