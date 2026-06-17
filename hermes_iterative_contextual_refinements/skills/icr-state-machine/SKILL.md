---
name: icr-state-machine
description: Inspect ICR React/LangGraph state machine parity, mode-state projections, transition logs, restore plans, and optimized replay indexes.
---

# ICR State Machine

Use this skill when reviewing whether a Hermes ICR run preserves the upstream React/LangGraph state machine shape.

## Artifact

Every completed or failed `icr_run` stores:

```text
artifacts.state_machine
```

The artifact includes:

- `versioned_state`: upstream `VersionedState`-compatible wrapper with `_version`, `_exportedAt`, `_mode`, and `data.modeState`.
- `exported_config`: legacy upstream `ExportedConfig` fields such as `currentMode`, `activeDeepthinkPipeline`, `activeAgenticState`, `activeContextualState`, `activeAdaptiveDeepthinkState`, and model parameters.
- `mode_state`: the active mode state returned by the corresponding upstream `ModeStateHandler`.
- `graph`: LangGraph nodes, reducers, conditional edges, and `shouldExit` for Agentic and Adaptive Deepthink; pipeline nodes for Deepthink, Contextual, and DCA.
- `transition_log`: ordered state creation, LLM calls, tool calls/results, record events, and terminal state.
- `indexes`: direct lookup tables for roles, purposes, branches, hypotheses, tools, final candidates, messages, and content versions.
- `restore_plan`: sanitizer and handler steps matching upstream import behavior.

## Review Checklist

For Deepthink and Evolving DFS:

- `mode_state.pipeline.initialStrategies` must contain upstream-style `strategyText`, `subStrategies`, branch version, memory, replacement history, and final judging fields.
- Evolving DFS first hypothesis round should use `globalIteration: 0`; initial branch execution should use global iteration 1.
- `structuredSolutionPoolAgents`, `memoryBankAgents`, `postQualityFilterAgents`, `hypothesisRounds`, and `strategySpecificKnowledgePackets` should be present when the run used those features.
- `indexes.branchIds`, `indexes.strategyIds`, and `indexes.finalCandidateIds` should allow replay without scanning the full artifact.

For Agentic:

- `graph.nodes` must be `agent` and `tools`.
- Conditional edges must represent `START -> agent -> tools? -> agent/END`.
- `graph.shouldExit` should be true only after verified Exit.
- `mode_state.graphState` should include `currentContent`, `contentHistory`, `verifierReports`, `verificationCount`, `lastVerifiedContent`, and `shouldExit`.

For Adaptive Deepthink:

- `graph.nodes` must be `agent` and `tools`.
- `mode_state.coreState` should preserve strategies, hypotheses, tests, executions, critiques, corrections, and selected solution.
- Rejected `Exit` calls must appear as error tool events and must not complete the run.
- `mode_state.deepthinkPipelineState` should project the adaptive core into a Deepthink UI state.

For Contextual:

- `mode_state` should include id, histories for all four agents, memory snapshots, strategic pools, `iterationCount`, `isProcessing`, `isRunning`, messages, and content history.

For DCA:

- `mode_state` should include id, problem, status, error, solutions, and `isStopRequested`.
- DCA pool size is limited to upstream's 10 rather than silently exceeding the source state machine.
