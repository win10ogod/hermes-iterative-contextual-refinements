"""Configuration validation for ICR modes.

The source ICR app clamps some UI controls. This plugin validates the same
limits explicitly and records mode-forced settings in the run artifact so a
run never looks more capable than the configuration actually used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import (
    CONTEXTUAL_RETRY_DELAYS_SECONDS,
    DEEPTHINK_MAIN_STRATEGY_MAX,
    DEEPTHINK_MAIN_STRATEGY_MIN,
    DCA_POOL_LIMIT_MAX,
    DEEPTHINK_RETRY_DELAYS_SECONDS,
    EVOLVING_DFS_DEPTH_MAX,
    EVOLVING_DFS_DEPTH_MIN,
    EVOLVING_DFS_MAIN_STRATEGY_MAX,
    HYPOTHESIS_MAX,
    HYPOTHESIS_MIN,
    MAX_API_ATTEMPTS,
    SUB_STRATEGY_ALLOWED_COUNTS,
)


@dataclass
class RoleModelOverride:
    provider: str | None = None
    model: str | None = None
    agent_id: str | None = None
    profile: str | None = None


@dataclass
class ICRConfig:
    main_strategies: int = 3
    sub_strategies: int = 0
    hypotheses: int = 3
    hypothesis_injection_mode: str = "strategy_aware"
    refinement: bool = True
    critique_synthesis: bool = False
    include_hypotheses_in_synthesis: bool = False
    full_solution_context: bool = False
    evolving_depth: int = 3
    pqf: bool = True
    pqf_aggressiveness: str = "balanced"
    max_api_attempts: int = MAX_API_ATTEMPTS
    retry_delays_seconds: tuple[float, ...] = DEEPTHINK_RETRY_DELAYS_SECONDS
    contextual_retry_delays_seconds: tuple[float, ...] = CONTEXTUAL_RETRY_DELAYS_SECONDS
    contextual_iterations: int = 3
    contextual_condensation_interval: int = 10
    adaptive_max_tool_turns: int = 16
    agentic_max_tool_turns: int = 48
    dca_pool_limit: int = 10
    python_execution_enabled: bool = False
    python_execution_timeout_seconds: float = 30.0
    model_call_timeout_seconds: float | None = None
    model_call_timeout_retry_seconds: float = 1200.0
    model_call_timeout_kwarg: str = "timeout_seconds"
    run_deadline_seconds: float | None = None
    heartbeat_stale_seconds: float | None = None
    python_execution_roles: tuple[str, ...] = (
        "hypothesis_testing",
        "solution_attempt",
        "solution_critique",
        "self_improvement",
    )
    role_overrides: dict[str, RoleModelOverride] = field(default_factory=dict)
    semantic_adjustments: list[str] = field(default_factory=list)

    def role(self, name: str) -> RoleModelOverride:
        return self.role_overrides.get(name, RoleModelOverride())

    def as_dict(self) -> dict[str, Any]:
        return {
            "main_strategies": self.main_strategies,
            "sub_strategies": self.sub_strategies,
            "hypotheses": self.hypotheses,
            "hypothesis_injection_mode": self.hypothesis_injection_mode,
            "refinement": self.refinement,
            "critique_synthesis": self.critique_synthesis,
            "include_hypotheses_in_synthesis": self.include_hypotheses_in_synthesis,
            "full_solution_context": self.full_solution_context,
            "evolving_depth": self.evolving_depth,
            "pqf": self.pqf,
            "pqf_aggressiveness": self.pqf_aggressiveness,
            "max_api_attempts": self.max_api_attempts,
            "retry_delays_seconds": list(self.retry_delays_seconds),
            "contextual_retry_delays_seconds": list(self.contextual_retry_delays_seconds),
            "contextual_iterations": self.contextual_iterations,
            "contextual_condensation_interval": self.contextual_condensation_interval,
            "adaptive_max_tool_turns": self.adaptive_max_tool_turns,
            "agentic_max_tool_turns": self.agentic_max_tool_turns,
            "dca_pool_limit": self.dca_pool_limit,
            "python_execution_enabled": self.python_execution_enabled,
            "python_execution_timeout_seconds": self.python_execution_timeout_seconds,
            "model_call_timeout_seconds": self.model_call_timeout_seconds,
            "model_call_timeout_retry_seconds": self.model_call_timeout_retry_seconds,
            "model_call_timeout_kwarg": self.model_call_timeout_kwarg,
            "run_deadline_seconds": self.run_deadline_seconds,
            "heartbeat_stale_seconds": self.heartbeat_stale_seconds,
            "python_execution_roles": list(self.python_execution_roles),
            "role_overrides": {
                role: {
                    "provider": override.provider,
                    "model": override.model,
                    "agent_id": override.agent_id,
                    "profile": override.profile,
                }
                for role, override in sorted(self.role_overrides.items())
            },
            "semantic_adjustments": list(self.semantic_adjustments),
        }


def _as_int(raw: Any, name: str, default: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    return value


def _as_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value: {raw!r}")
    return bool(raw)


def _as_delays(raw: Any, default: tuple[float, ...], *, name: str, expected: int) -> tuple[float, ...]:
    if raw is None:
        return default
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{name} must be a list of seconds")
    delays = tuple(float(item) for item in raw)
    if len(delays) != expected:
        raise ValueError(f"{name} must contain exactly {expected} retry delays")
    if any(delay < 0 for delay in delays):
        raise ValueError(f"{name} must contain only non-negative delays")
    return delays


def _as_str_tuple(raw: Any, name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return default
    if isinstance(raw, str):
        values = tuple(part.strip() for part in raw.split(",") if part.strip())
    elif isinstance(raw, (list, tuple)):
        values = tuple(str(part).strip() for part in raw if str(part).strip())
    else:
        raise ValueError(f"{name} must be a string or list of strings")
    if not values:
        raise ValueError(f"{name} must contain at least one value")
    return values


def _as_optional_positive_float(raw: Any, name: str, default: float | None) -> float | None:
    if raw is None or raw == "":
        return default
    value = float(raw)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value or None


def _as_nonnegative_float(raw: Any, name: str, default: float) -> float:
    if raw is None or raw == "":
        return default
    value = float(raw)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _parse_role_overrides(raw: Any) -> dict[str, RoleModelOverride]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("role_overrides must be an object")
    result: dict[str, RoleModelOverride] = {}
    for role, value in raw.items():
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role_overrides keys must be role names")
        if not isinstance(value, dict):
            raise ValueError(f"role_overrides.{role} must be an object")
        result[role] = RoleModelOverride(
            provider=value.get("provider"),
            model=value.get("model"),
            agent_id=value.get("agent_id"),
            profile=value.get("profile"),
        )
    return result


def build_config(raw: dict[str, Any] | None, *, mode: str) -> ICRConfig:
    data = dict(raw or {})
    cfg = ICRConfig(
        main_strategies=_as_int(data.get("main_strategies"), "main_strategies", 3),
        sub_strategies=_as_int(data.get("sub_strategies"), "sub_strategies", 0),
        hypotheses=_as_int(data.get("hypotheses"), "hypotheses", 3),
        hypothesis_injection_mode=str(data.get("hypothesis_injection_mode", "strategy_aware")),
        refinement=_as_bool(data.get("refinement"), True),
        critique_synthesis=_as_bool(data.get("critique_synthesis"), False),
        include_hypotheses_in_synthesis=_as_bool(data.get("include_hypotheses_in_synthesis"), False),
        full_solution_context=_as_bool(data.get("full_solution_context"), False),
        evolving_depth=_as_int(data.get("evolving_depth"), "evolving_depth", 3),
        pqf=_as_bool(data.get("pqf"), True),
        pqf_aggressiveness=str(data.get("pqf_aggressiveness", "balanced")).lower(),
        max_api_attempts=_as_int(data.get("max_api_attempts"), "max_api_attempts", MAX_API_ATTEMPTS),
        retry_delays_seconds=_as_delays(
            data.get("retry_delays_seconds"),
            DEEPTHINK_RETRY_DELAYS_SECONDS,
            name="retry_delays_seconds",
            expected=3,
        ),
        contextual_retry_delays_seconds=_as_delays(
            data.get("contextual_retry_delays_seconds"),
            CONTEXTUAL_RETRY_DELAYS_SECONDS,
            name="contextual_retry_delays_seconds",
            expected=2,
        ),
        contextual_iterations=_as_int(data.get("contextual_iterations"), "contextual_iterations", 3),
        contextual_condensation_interval=_as_int(data.get("contextual_condensation_interval"), "contextual_condensation_interval", 10),
        adaptive_max_tool_turns=_as_int(data.get("adaptive_max_tool_turns"), "adaptive_max_tool_turns", 16),
        agentic_max_tool_turns=_as_int(data.get("agentic_max_tool_turns"), "agentic_max_tool_turns", 48),
        dca_pool_limit=_as_int(data.get("dca_pool_limit"), "dca_pool_limit", 10),
        python_execution_enabled=_as_bool(data.get("python_execution_enabled"), False),
        python_execution_timeout_seconds=float(data.get("python_execution_timeout_seconds", 30.0)),
        model_call_timeout_seconds=_as_optional_positive_float(
            data.get("model_call_timeout_seconds"),
            "model_call_timeout_seconds",
            None,
        ),
        model_call_timeout_retry_seconds=_as_nonnegative_float(
            data.get("model_call_timeout_retry_seconds"),
            "model_call_timeout_retry_seconds",
            1200.0,
        ),
        model_call_timeout_kwarg=str(data.get("model_call_timeout_kwarg", "timeout_seconds") or "timeout_seconds"),
        run_deadline_seconds=_as_optional_positive_float(
            data.get("run_deadline_seconds"),
            "run_deadline_seconds",
            None,
        ),
        heartbeat_stale_seconds=_as_optional_positive_float(
            data.get("heartbeat_stale_seconds"),
            "heartbeat_stale_seconds",
            None,
        ),
        python_execution_roles=_as_str_tuple(
            data.get("python_execution_roles"),
            "python_execution_roles",
            (
                "hypothesis_testing",
                "solution_attempt",
                "solution_critique",
                "self_improvement",
            ),
        ),
        role_overrides=_parse_role_overrides(data.get("role_overrides")),
    )

    if cfg.max_api_attempts != MAX_API_ATTEMPTS:
        raise ValueError("max_api_attempts must remain 4 to preserve ICR retry semantics")
    if not DEEPTHINK_MAIN_STRATEGY_MIN <= cfg.main_strategies <= DEEPTHINK_MAIN_STRATEGY_MAX:
        raise ValueError("main_strategies must be between 1 and 10")
    if cfg.sub_strategies not in SUB_STRATEGY_ALLOWED_COUNTS:
        raise ValueError("sub_strategies must be one of 0, 2, 3, 4, or 5")
    if not HYPOTHESIS_MIN <= cfg.hypotheses <= HYPOTHESIS_MAX:
        raise ValueError("hypotheses must be between 0 and 6")
    if cfg.hypothesis_injection_mode not in {"parallel", "strategy_aware", "selective_injection"}:
        raise ValueError("hypothesis_injection_mode must be parallel, strategy_aware, or selective_injection")
    if not EVOLVING_DFS_DEPTH_MIN <= cfg.evolving_depth <= EVOLVING_DFS_DEPTH_MAX:
        raise ValueError("evolving_depth must be between 1 and 10")
    if cfg.pqf_aggressiveness not in {"balanced", "aggressive"}:
        raise ValueError("pqf_aggressiveness must be balanced or aggressive")
    if cfg.contextual_iterations < 1:
        raise ValueError("contextual_iterations must be positive")
    if cfg.contextual_condensation_interval < 1:
        raise ValueError("contextual_condensation_interval must be positive")
    if cfg.adaptive_max_tool_turns < 1:
        raise ValueError("adaptive_max_tool_turns must be positive")
    if cfg.agentic_max_tool_turns < 1:
        raise ValueError("agentic_max_tool_turns must be positive")
    if cfg.dca_pool_limit < 1:
        raise ValueError("dca_pool_limit must be positive")
    if cfg.dca_pool_limit > DCA_POOL_LIMIT_MAX:
        raise ValueError("dca_pool_limit must be between 1 and 10 to match upstream DCA")
    if cfg.python_execution_timeout_seconds <= 0:
        raise ValueError("python_execution_timeout_seconds must be positive")
    if cfg.model_call_timeout_kwarg not in {"timeout_seconds", "timeout", "request_timeout", "read_timeout"}:
        raise ValueError("model_call_timeout_kwarg must be timeout_seconds, timeout, request_timeout, or read_timeout")
    if not cfg.python_execution_roles:
        raise ValueError("python_execution_roles must contain at least one role when configured")

    if mode == "evolving_deepthink":
        if cfg.main_strategies > EVOLVING_DFS_MAIN_STRATEGY_MAX:
            raise ValueError("evolving_deepthink supports 1-5 main strategies")
        if cfg.sub_strategies != 0:
            cfg.sub_strategies = 0
            cfg.semantic_adjustments.append("Evolving DFS forces sub_strategies to 0.")
        if not cfg.refinement:
            cfg.refinement = True
            cfg.semantic_adjustments.append("Evolving DFS requires refinement.")
        if not cfg.pqf:
            cfg.pqf = True
            cfg.semantic_adjustments.append("Evolving DFS forces PQF on.")
        if cfg.hypothesis_injection_mode != "selective_injection":
            cfg.hypothesis_injection_mode = "selective_injection"
            cfg.semantic_adjustments.append("Evolving DFS forces selective hypothesis routing.")
        if cfg.critique_synthesis:
            cfg.critique_synthesis = False
            cfg.semantic_adjustments.append("Critique synthesis is disabled in Evolving DFS.")
        if cfg.full_solution_context:
            cfg.full_solution_context = False
            cfg.semantic_adjustments.append("Full solution context is disabled in Evolving DFS.")

    return cfg
