---
name: icr-contextual-refinement
description: Run and inspect contextual refinement with main generator, iterative agent, strategic pool, memory agent, and condensation behavior.
---

# ICR Contextual Refinement

Use `contextual_refinement` when the user wants repeated improvement of an output through a generator, critique agent, strategic pool agent, and memory condensation.

## Loop Semantics

Each iteration runs:

1. Main Generator produces or revises the current best generation.
2. Iterative Agent critiques the generation and tool executions if present.
3. Strategic Pool Agent studies the generation and critique, then evolves unexplored strategies.
4. Main Generator receives the critique plus strategic pool for the next iteration.
5. After the configured condensation interval, Memory Agent condenses recent generator/critique turns and previous memory snapshots.

## Histories

The mode maintains separate histories:

- `main_generator_history`
- `iterative_agent_history`
- `strategic_pool_agent_history`
- `memory_agent_history`

Do not merge these histories into one transcript. The isolation is part of the mode behavior.

## Condensation

Default condensation interval is 10 turns. The memory agent should create an evolving document covering:

- What worked.
- What failed.
- Persistent issues.
- Useful techniques.
- Guidance for future generations.

After condensation, the working histories are rebuilt around the initial request, the memory summary, the latest generation, critique, and strategic-pool context. This keeps long runs from treating all raw turns as equally authoritative.

## Run Example

```json
{
  "mode": "contextual_refinement",
  "challenge": "Improve this product specification...",
  "config": {
    "contextual_iterations": 4,
    "contextual_condensation_interval": 2
  }
}
```

## Review Checklist

Check the saved artifact for:

- `contextual_state.messages` containing main generator, iterative agent, strategic pool agent, and memory agent entries when condensation is due.
- `memory_snapshots` preserving condensation points.
- `content_history` preserving generated content across iterations.
- `final.content` matching the latest current best generation.

