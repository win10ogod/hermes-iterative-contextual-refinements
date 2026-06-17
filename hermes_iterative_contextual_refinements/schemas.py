"""JSON schemas for Hermes tools and structured model calls."""

from __future__ import annotations

from .constants import ICR_MODES


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
                    "type": "object",
                    "description": "Mode configuration. Counts outside documented ICR limits are rejected.",
                    "additionalProperties": True,
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
