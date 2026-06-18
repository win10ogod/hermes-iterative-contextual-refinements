"""JSON schemas for Hermes tools and structured model calls."""

from __future__ import annotations

from .constants import (
    DEEPTHINK_MAIN_STRATEGY_MAX,
    DEEPTHINK_MAIN_STRATEGY_MIN,
    EVOLVING_DFS_DEPTH_MAX,
    EVOLVING_DFS_DEPTH_MIN,
    HYPOTHESIS_MAX,
    HYPOTHESIS_MIN,
    ICR_MODES,
    MAX_API_ATTEMPTS,
)


def icr_run_schema() -> dict:
    return {
        "name": "icr_run",
        "description": "Run an Iterative Contextual Refinements mode through Hermes-owned LLM access.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": list(ICR_MODES),
                    "description": "ICR mode to run.",
                },
                "challenge": {
                    "type": "string",
                    "description": "Core challenge or user request for all non-agentic modes.",
                },
                "content": {
                    "type": "string",
                    "description": "Initial mutable draft for agentic_refinement.",
                },
                "instruction": {
                    "type": "string",
                    "description": "Optional agentic refinement instruction.",
                },
                "config": {
                    **icr_config_schema(),
                    "description": "Mode configuration. Counts outside documented ICR limits are rejected.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional externally supplied run id.",
                },
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    }


def icr_start_schema() -> dict:
    schema = icr_run_schema()
    schema["name"] = "icr_start"
    schema["description"] = (
        "Start an Iterative Contextual Refinements run in the Hermes plugin process and return immediately. "
        "Use icr_status to poll progress and icr_export to retrieve completed results."
    )
    return schema


def icr_config_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "main_strategies": {"type": "integer", "minimum": DEEPTHINK_MAIN_STRATEGY_MIN, "maximum": DEEPTHINK_MAIN_STRATEGY_MAX},
            "sub_strategies": {"type": "integer", "enum": [0, 2, 3, 4, 5]},
            "hypotheses": {"type": "integer", "minimum": HYPOTHESIS_MIN, "maximum": HYPOTHESIS_MAX},
            "hypothesis_injection_mode": {"type": "string", "enum": ["parallel", "strategy_aware", "selective_injection"]},
            "refinement": {"type": "boolean"},
            "critique_synthesis": {"type": "boolean"},
            "include_hypotheses_in_synthesis": {"type": "boolean"},
            "full_solution_context": {"type": "boolean"},
            "evolving_depth": {"type": "integer", "minimum": EVOLVING_DFS_DEPTH_MIN, "maximum": EVOLVING_DFS_DEPTH_MAX},
            "pqf": {"type": "boolean"},
            "pqf_aggressiveness": {"type": "string", "enum": ["balanced", "aggressive"]},
            "max_api_attempts": {"type": "integer", "const": MAX_API_ATTEMPTS},
            "retry_delays_seconds": {
                "type": "array",
                "items": {"type": "number", "minimum": 0},
                "minItems": 3,
                "maxItems": 3,
            },
            "contextual_retry_delays_seconds": {
                "type": "array",
                "items": {"type": "number", "minimum": 0},
                "minItems": 2,
                "maxItems": 2,
            },
            "contextual_iterations": {"type": "integer", "minimum": 1},
            "contextual_condensation_interval": {"type": "integer", "minimum": 1},
            "adaptive_max_tool_turns": {"type": "integer", "minimum": 1},
            "agentic_max_tool_turns": {"type": "integer", "minimum": 1},
            "dca_pool_limit": {"type": "integer", "minimum": 1},
            "python_execution_enabled": {"type": "boolean"},
            "python_execution_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
            "model_call_timeout_seconds": {
                "type": "number",
                "minimum": 0,
                "description": "Optional per-call timeout for host LLM requests. 0 or omitted keeps the host default.",
            },
            "model_call_timeout_retry_seconds": {
                "type": "number",
                "minimum": 0,
                "description": "Timeout applied on retries after a timeout error. 0 disables timeout retry override.",
            },
            "model_call_timeout_kwarg": {
                "type": "string",
                "enum": ["timeout_seconds", "timeout", "request_timeout", "read_timeout"],
                "description": "Keyword used when passing the timeout to ctx.llm.",
            },
            "run_deadline_seconds": {
                "type": "number",
                "minimum": 0,
                "description": "Optional whole-run deadline. 0 or omitted disables the deadline.",
            },
            "heartbeat_stale_seconds": {
                "type": "number",
                "minimum": 0,
                "description": "Optional stale-progress limit. When exceeded, the heartbeat stops refreshing gateway activity so a real stall is not hidden.",
            },
            "python_execution_roles": {
                "oneOf": [
                    {"type": "string", "description": "Single role or comma-separated roles."},
                    {"type": "array", "items": {"type": "string"}, "minItems": 1},
                ]
            },
            "role_overrides": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "model": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "profile": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": True,
    }


def icr_status_schema() -> dict:
    return {
        "name": "icr_status",
        "description": "Return status and metadata for a saved ICR run.",
        "parameters": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    }


def icr_export_schema() -> dict:
    return {
        "name": "icr_export",
        "description": "Export an ICR run as JSON or Markdown summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "markdown"], "default": "json"},
                "output_path": {"type": "string", "description": "Optional file path to write the export."},
            },
            "required": ["run_id"],
            "additionalProperties": False,
        },
    }


def icr_list_runs_schema() -> dict:
    return {
        "name": "icr_list_runs",
        "description": "List recent ICR runs saved under HERMES_HOME.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                "status": {"type": "string", "description": "Optional status filter."},
                "mode": {"type": "string", "enum": list(ICR_MODES), "description": "Optional mode filter."},
            },
            "additionalProperties": False,
        },
    }


STRATEGIES_SCHEMA = {
    "type": "object",
    "properties": {"strategies": {"type": "array", "items": {"type": "string"}}},
    "required": ["strategies"],
    "additionalProperties": True,
}

SUB_STRATEGIES_SCHEMA = {
    "type": "object",
    "properties": {"sub_strategies": {"type": "array", "items": {"type": "string"}}},
    "required": ["sub_strategies"],
    "additionalProperties": True,
}

HYPOTHESES_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "target_strategies": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["hypotheses"],
    "additionalProperties": True,
}

SOLUTION_POOL_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy_id": {"type": "string"},
        "solutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "confidence": {"type": "number"},
                    "internal_critique": {"type": "string"},
                    "key_insights": {"type": "string"},
                },
                "required": ["title", "content", "confidence", "internal_critique"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["solutions"],
    "additionalProperties": True,
}

PQF_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis_summary": {"type": "string"},
        "strategies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["keep", "update"]},
                    "reasoning": {"type": "string"},
                },
                "required": ["strategy_id", "decision", "reasoning"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["strategies"],
    "additionalProperties": True,
}

STRATEGY_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "strategies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "string"},
                    "strategy": {"type": "string"},
                },
                "required": ["strategy_id", "strategy"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["strategies"],
    "additionalProperties": True,
}

ADAPTIVE_ORCHESTRATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "assistant_text": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object", "additionalProperties": True},
                },
                "required": ["name", "arguments"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["tool_calls"],
    "additionalProperties": True,
}

AGENTIC_ORCHESTRATOR_SCHEMA = ADAPTIVE_ORCHESTRATOR_SCHEMA

DCA_POOL_SCHEMA = {
    "type": "object",
    "properties": {
        "solutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "priority": {"type": "integer"},
                },
                "required": ["title", "content"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["solutions"],
    "additionalProperties": True,
}

DCA_LOCAL_SCHEMA = {
    "type": "object",
    "properties": {
        "evolutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["title", "content"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["evolutions"],
    "additionalProperties": True,
}
