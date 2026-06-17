"""Host-owned LLM wrapper with ICR retry and artifact recording."""

from __future__ import annotations

import inspect
import time
import threading
import uuid
from typing import Any

from .config import ICRConfig
from .json_utils import as_text, parse_json_object, utc_now_iso
from .python_runtime import PythonExecutionManager, extract_python_blocks, format_python_results


_TIMEOUT_KWARG_ALIASES = ("timeout_seconds", "timeout", "request_timeout", "read_timeout")


class ICRLlm:
    def __init__(self, ctx_llm: Any, record: dict[str, Any], config: ICRConfig):
        self.ctx_llm = ctx_llm
        self.record = record
        self.config = config
        self._lock = threading.RLock()
        self._python = PythonExecutionManager(record, config.python_execution_timeout_seconds)

    def close(self) -> None:
        self._python.close_all()

    def _override_kwargs(self, role: str) -> dict[str, Any]:
        override = self.config.role(role)
        return {
            "provider": override.provider,
            "model": override.model,
            "agent_id": override.agent_id,
            "profile": override.profile,
        }

    def _timeout_for_attempt(self, previous_error: BaseException | None) -> float | None:
        configured = self.config.model_call_timeout_seconds
        if previous_error is not None and _is_timeout_error(previous_error):
            retry_timeout = self.config.model_call_timeout_retry_seconds
            if retry_timeout > 0:
                return max(configured or 0.0, retry_timeout)
        return configured

    def _timeout_kwargs(self, method: Any, timeout_seconds: float | None) -> tuple[dict[str, Any], str | None]:
        if timeout_seconds is None or timeout_seconds <= 0:
            return {}, None
        preferred = self.config.model_call_timeout_kwarg
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return {preferred: timeout_seconds}, preferred
        params = signature.parameters
        if preferred in params or any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
            return {preferred: timeout_seconds}, preferred
        for name in _TIMEOUT_KWARG_ALIASES:
            if name in params:
                return {name: timeout_seconds}, name
        return {}, None

    def _invoke_ctx(self, method: Any, args: tuple[Any, ...] = (), *, timeout_seconds: float | None = None, **kwargs: Any) -> tuple[Any, str | None]:
        timeout_kwargs, timeout_kwarg = self._timeout_kwargs(method, timeout_seconds)
        if timeout_seconds is not None and timeout_seconds > 0 and not timeout_kwargs:
            raise RuntimeError(
                f"ctx.llm method {getattr(method, '__name__', method)!r} does not accept a supported timeout keyword; "
                "set model_call_timeout_kwarg to timeout_seconds, timeout, request_timeout, or read_timeout if the host supports one."
            )
        try:
            return method(*args, **kwargs, **timeout_kwargs), timeout_kwarg
        except TypeError as exc:
            if timeout_kwargs and _looks_like_unexpected_timeout_kwarg(exc, next(iter(timeout_kwargs))):
                raise RuntimeError(
                    f"ctx.llm rejected timeout keyword {next(iter(timeout_kwargs))!r}; "
                    "set config.model_call_timeout_kwarg to the keyword supported by this Hermes LLM provider."
                ) from exc
            raise

    def _usage_dict(self, result: Any) -> dict[str, Any]:
        usage = getattr(result, "usage", None)
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return dict(usage)
        return {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            "cache_read_tokens": int(getattr(usage, "cache_read_tokens", 0) or 0),
            "cache_write_tokens": int(getattr(usage, "cache_write_tokens", 0) or 0),
            "cost_usd": getattr(usage, "cost_usd", None),
        }

    def _accumulate_usage(self, usage: dict[str, Any]) -> None:
        with self._lock:
            totals = self.record.setdefault("usage", {})
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                totals[key] = int(totals.get(key, 0) or 0) + int(usage.get(key, 0) or 0)
            if usage.get("cost_usd") is not None:
                totals["cost_usd"] = float(totals.get("cost_usd", 0.0) or 0.0) + float(usage["cost_usd"])

    def _record_call(self, call: dict[str, Any]) -> None:
        with self._lock:
            self.record.setdefault("llm_calls", []).append(call)
            self.record["updated_at"] = utc_now_iso()

    def complete(self, *, role: str, purpose: str, prompt: str, system_prompt: str = "", temperature: float | None = None) -> str:
        call = {
            "id": f"call-{uuid.uuid4().hex[:10]}",
            "role": role,
            "purpose": purpose,
            "kind": "text",
            "status": "processing",
            "created_at": utc_now_iso(),
            "raw_prompt": prompt,
            "system_prompt": system_prompt,
            "attempts": [],
        }
        messages = []
        effective_system_prompt = self._system_prompt_with_python(role, system_prompt)
        if effective_system_prompt:
            messages.append({"role": "system", "content": effective_system_prompt})
        messages.append({"role": "user", "content": prompt})
        last_error: BaseException | None = None
        for attempt in range(1, self.config.max_api_attempts + 1):
            timeout_seconds = self._timeout_for_attempt(last_error)
            attempt_data: dict[str, Any] = {"attempt": attempt, "timeout_seconds": timeout_seconds}
            try:
                result, timeout_kwarg = self._invoke_ctx(
                    self.ctx_llm.complete,
                    (messages,),
                    timeout_seconds=timeout_seconds,
                    temperature=temperature,
                    purpose=purpose,
                    **self._override_kwargs(role),
                )
                if timeout_kwarg:
                    attempt_data["timeout_kwarg"] = timeout_kwarg
                text = as_text(getattr(result, "text", ""))
                usage = self._usage_dict(result)
                self._accumulate_usage(usage)
                python_details: dict[str, Any] = {}
                final_text = text
                if self._python_enabled_for(role):
                    final_text, python_details = self._finalize_python_assisted_text(
                        role=role,
                        purpose=purpose,
                        messages=messages,
                        first_text=text,
                        timeout_seconds=timeout_seconds,
                    )
                call.update(
                    {
                        "status": "completed",
                        "completed_at": utc_now_iso(),
                        "attempt_count": attempt,
                        "raw_response": final_text,
                        "parsed_data": None,
                        "provider": getattr(result, "provider", ""),
                        "model": getattr(result, "model", ""),
                        "usage": usage,
                        "audit": getattr(result, "audit", {}),
                        **python_details,
                    }
                )
                attempt_data["status"] = "completed"
                call["attempts"].append(attempt_data)
                self._record_call(call)
                return final_text
            except BaseException as exc:
                last_error = exc
                attempt_data.update({"status": "error", "error": str(exc), "error_type": type(exc).__name__, "is_timeout": _is_timeout_error(exc)})
                call["attempts"].append(attempt_data)
                if attempt < self.config.max_api_attempts:
                    delay = self.config.retry_delays_seconds[attempt - 1]
                    if delay > 0:
                        time.sleep(delay)
        call.update(
            {
                "status": "error",
                "completed_at": utc_now_iso(),
                "attempt_count": self.config.max_api_attempts,
                "errors": [str(last_error)] if last_error else ["Unknown LLM error"],
            }
        )
        self._record_call(call)
        raise RuntimeError(f"{purpose} failed after {self.config.max_api_attempts} attempts: {last_error}")

    def _python_enabled_for(self, role: str) -> bool:
        return self.config.python_execution_enabled and role in set(self.config.python_execution_roles)

    def _system_prompt_with_python(self, role: str, system_prompt: str) -> str:
        if not self._python_enabled_for(role):
            return system_prompt
        python_note = (
            "Python execution is available for this ICR role. When executable verification, "
            "calculation, data processing, or image/file generation would materially improve "
            "the result, include one or more fenced ```python``` blocks. The plugin will run "
            "them in this role's persistent isolated Python session and ask you to produce a "
            "final answer from the execution output. Do not print raw binary or base64 data."
        )
        return "\n\n".join(part for part in (system_prompt, python_note) if part)

    def _finalize_python_assisted_text(
        self,
        *,
        role: str,
        purpose: str,
        messages: list[dict[str, Any]],
        first_text: str,
        timeout_seconds: float | None,
    ) -> tuple[str, dict[str, Any]]:
        blocks = extract_python_blocks(first_text)
        if not blocks:
            return first_text, {}
        results = self._python.execute_blocks(role=role, blocks=blocks)
        followup_messages = list(messages)
        followup_messages.append({"role": "assistant", "content": first_text})
        followup_messages.append(
            {
                "role": "user",
                "content": (
                    "The Python blocks above were executed in your persistent role session. "
                    "Use the execution evidence below to produce the final role output. "
                    "Do not repeat raw code unless it is part of the requested answer.\n\n"
                    f"{format_python_results(results)}"
                ),
            }
        )
        result, timeout_kwarg = self._invoke_ctx(
            self.ctx_llm.complete,
            (followup_messages,),
            timeout_seconds=timeout_seconds,
            purpose=f"{purpose}.python_finalization",
            **self._override_kwargs(role),
        )
        usage = self._usage_dict(result)
        self._accumulate_usage(usage)
        return (
            as_text(getattr(result, "text", "")),
            {
                "raw_response_before_python": first_text,
                "python_executions": results,
                "python_finalization_usage": usage,
                "python_finalization_provider": getattr(result, "provider", ""),
                "python_finalization_model": getattr(result, "model", ""),
                "python_finalization_timeout_seconds": timeout_seconds,
                "python_finalization_timeout_kwarg": timeout_kwarg,
            },
        )

    def structured(
        self,
        *,
        role: str,
        purpose: str,
        instructions: str,
        prompt: str,
        schema: dict[str, Any] | None = None,
        system_prompt: str = "",
        temperature: float | None = None,
    ) -> dict[str, Any]:
        call = {
            "id": f"call-{uuid.uuid4().hex[:10]}",
            "role": role,
            "purpose": purpose,
            "kind": "structured",
            "status": "processing",
            "created_at": utc_now_iso(),
            "raw_prompt": prompt,
            "instructions": instructions,
            "system_prompt": system_prompt,
            "json_schema": schema,
            "attempts": [],
        }
        last_error: BaseException | None = None
        for attempt in range(1, self.config.max_api_attempts + 1):
            timeout_seconds = self._timeout_for_attempt(last_error)
            attempt_data: dict[str, Any] = {"attempt": attempt, "timeout_seconds": timeout_seconds}
            try:
                result, timeout_kwarg = self._invoke_ctx(
                    self.ctx_llm.complete_structured,
                    timeout_seconds=timeout_seconds,
                    instructions=instructions,
                    input=[{"type": "text", "text": prompt}],
                    json_schema=schema,
                    json_mode=True,
                    schema_name=purpose,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    purpose=purpose,
                    **self._override_kwargs(role),
                )
                if timeout_kwarg:
                    attempt_data["timeout_kwarg"] = timeout_kwarg
                text = as_text(getattr(result, "text", ""))
                parsed = getattr(result, "parsed", None)
                if parsed is None:
                    parsed = parse_json_object(text)
                if not isinstance(parsed, dict):
                    raise ValueError("Structured LLM response was not a JSON object")
                usage = self._usage_dict(result)
                self._accumulate_usage(usage)
                call.update(
                    {
                        "status": "completed",
                        "completed_at": utc_now_iso(),
                        "attempt_count": attempt,
                        "raw_response": text,
                        "parsed_data": parsed,
                        "provider": getattr(result, "provider", ""),
                        "model": getattr(result, "model", ""),
                        "usage": usage,
                        "audit": getattr(result, "audit", {}),
                    }
                )
                attempt_data["status"] = "completed"
                call["attempts"].append(attempt_data)
                self._record_call(call)
                return parsed
            except BaseException as exc:
                last_error = exc
                attempt_data.update({"status": "error", "error": str(exc), "error_type": type(exc).__name__, "is_timeout": _is_timeout_error(exc)})
                call["attempts"].append(attempt_data)
                if attempt < self.config.max_api_attempts:
                    delay = self.config.retry_delays_seconds[attempt - 1]
                    if delay > 0:
                        time.sleep(delay)
        call.update(
            {
                "status": "error",
                "completed_at": utc_now_iso(),
                "attempt_count": self.config.max_api_attempts,
                "errors": [str(last_error)] if last_error else ["Unknown LLM error"],
            }
        )
        self._record_call(call)
        raise RuntimeError(f"{purpose} failed after {self.config.max_api_attempts} attempts: {last_error}")


def _is_timeout_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return (
        isinstance(exc, TimeoutError)
        or "timeout" in name
        or "timed out" in text
        or "timeout" in text
        or "deadline" in text
    )


def _looks_like_unexpected_timeout_kwarg(exc: TypeError, keyword: str) -> bool:
    text = str(exc)
    return keyword in text and (
        "unexpected keyword" in text
        or "got an unexpected" in text
        or "invalid keyword" in text
        or "not supported" in text
    )
