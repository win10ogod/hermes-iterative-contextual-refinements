---
name: icr-deepthink
description: Operate Deepthink single-pass and Evolving DFS modes while preserving strategy slots, branch versions, solution pools, memory, PQF, heartbeat, and final judge boundaries.
---

# ICR Deepthink

Use this skill for Deepthink runs.

## Single-Pass Strategic Pipeline

The `deepthink` mode runs:

1. Initial Strategy Generator.
2. Optional Sub-Strategy Generator per main strategy.
3. Hypothesis Generator and independent Hypothesis Testers.
4. Solution Attempt per branch.
5. Critique per solution when refinement is enabled.
6. Optional Dissected Observations Synthesis.
7. Optional Full Solution Context passed to correctors.
8. Self-Improvement per branch.
9. Final Judge.

Steps that operate on multiple branches or hypotheses run as same-stage concurrent work while preserving the saved artifact order.

The final judge receives candidate solution texts only. It must not receive critique volume, solution pool confidence, memory, hypothesis routing, PQF decisions, or replacement history.

## Evolving DFS

Use `evolving_deepthink` for persistent search. It preserves:

- Stable strategy slots such as `main1`, `main2`, `main3`.
- `branchVersion`, incremented only when PQF replaces a strategy in that slot.
- Branch-local iteration and global iteration as separate counters.
- Branch-local history and solution-pool history.
- Recursive memory bank after each five-entry window.
- PQF keep/update decisions grouped in pairs.
- Replacement archive with old strategy, latest solution, latest critique, memory, branch history, pool history, PQF reason, and version metadata.
- Hypothesis heartbeat every two global iterations.

## Evolving DFS Rules

- Main strategies are limited to 1-5.
- Sub-strategies are forced to 0.
- PQF is forced on.
- Hypothesis routing is forced to selective injection.
- Critique synthesis and full solution context are disabled.
- Depth includes the initial execution/critique as iteration 1.

## Python Execution

When the task needs executable checks, enable Python for the relevant roles:

```json
{
  "config": {
    "python_execution_enabled": true,
    "python_execution_roles": ["hypothesis_testing", "solution_attempt", "self_improvement"]
  }
}
```

The role may emit fenced `python` blocks. The plugin executes them, stores stdout/stderr/errors in the run artifact, then asks the role to produce its final output from that evidence. Do not enable Python merely to make normal prose generation look more capable.

## Maintenance

After a branch accumulates five undistilled history entries:

- Memory Bank receives only that branch, previous memory, and the next five raw history entries.
- PQF receives recent correction/critique history only for assigned due strategies plus active strategy texts.
- If PQF returns `update`, Strategy Update Generator creates replacement strategies in one consolidated call.
- A replacement branch starts clean with the same stable slot, incremented branch version, empty active history, empty pool history, no memory, and flushed strategy-specific hypotheses.
- The replacement gets initial execution and critique immediately. It does not receive an immediate solution pool until the next normal solution-pool stage.

## Review Checklist

When reviewing a Deepthink artifact, check:

- The final judge input contains only candidate texts.
- Replaced branches are archived but absent from active final candidates.
- Hypothesis heartbeat prompt does not consume current concurrent solution-pool outputs.
- Memory and PQF received different curated context.
- Branch version increments on replacement and branch-local iteration resets.
