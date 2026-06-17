"""Persistence and export for ICR run artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .json_utils import dumps


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


class RunStore:
    def __init__(self, base: Path | None = None):
        self.base = base or hermes_home() / "icr" / "runs"
        self.base.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in {"-", "_"})
        if not safe:
            raise ValueError("Invalid run_id")
        return self.base / f"{safe}.json"

    def save(self, record: dict[str, Any]) -> Path:
        path = self.path_for(record["run_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_name = handle.name
                handle.write(dumps(record))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if tmp_name:
                try:
                    Path(tmp_name).unlink(missing_ok=True)
                except OSError:
                    pass
        return path

    def load(self, run_id: str) -> dict[str, Any]:
        path = self.path_for(run_id)
        if not path.exists():
            raise FileNotFoundError(f"ICR run not found: {run_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid run file: {path}")
        return data

    def list_runs(self, *, limit: int = 20, status: str | None = None, mode: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if status and data.get("status") != status:
                continue
            if mode and data.get("mode") != mode:
                continue
            rows.append(
                {
                    "run_id": data.get("run_id"),
                    "mode": data.get("mode"),
                    "status": data.get("status"),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "path": str(path),
                    "final_summary": _short_summary(data),
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def export_json(self, run_id: str) -> str:
        return dumps(self.load(run_id))

    def export_markdown(self, run_id: str) -> str:
        run = self.load(run_id)
        artifacts = run.get("artifacts", {})
        final = artifacts.get("final") or artifacts.get("selected_solution") or artifacts.get("final_content") or {}
        lines = [
            f"# ICR Run {run.get('run_id')}",
            "",
            f"- Mode: `{run.get('mode')}`",
            f"- Status: `{run.get('status')}`",
            f"- Created: {run.get('created_at')}",
            f"- Updated: {run.get('updated_at')}",
            f"- LLM calls: {len(run.get('llm_calls', []))}",
            "",
            "## Request",
            "",
            dumps(run.get("request", {})),
            "",
            "## Final",
            "",
            _markdown_final(final),
            "",
            "## Errors",
            "",
            dumps(run.get("errors", [])),
        ]
        return "\n".join(lines)


def _short_summary(run: dict[str, Any]) -> str:
    artifacts = run.get("artifacts", {})
    final = artifacts.get("final") or artifacts.get("selected_solution") or artifacts.get("final_content") or {}
    text = _markdown_final(final).replace("\n", " ").strip()
    return text[:180]


def _markdown_final(final: Any) -> str:
    if isinstance(final, str):
        return final
    if isinstance(final, dict):
        for key in ("selected_solution", "content", "text", "judge_response", "final_content"):
            if final.get(key):
                return str(final[key])
        return "```json\n" + dumps(final) + "\n```"
    if final:
        return str(final)
    return "No final artifact recorded."
