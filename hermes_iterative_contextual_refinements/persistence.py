"""Persistence and export for ICR run artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
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

    def blob_dir_for(self, run_id: str) -> Path:
        return self.base.parent / "blobs" / self.path_for(run_id).stem

    def save(self, record: dict[str, Any]) -> Path:
        record = self._prepare_for_save(record)
        path = self.path_for(record["run_id"])
        self._atomic_write_json(path, record)
        return path

    def load(self, run_id: str) -> dict[str, Any]:
        path = self.path_for(run_id)
        if not path.exists():
            raise FileNotFoundError(f"ICR run not found: {run_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid run file: {path}")
        return self._resolve_blobs(data)

    def _prepare_for_save(self, record: dict[str, Any]) -> dict[str, Any]:
        snapshot = deepcopy(record)
        run_id = snapshot["run_id"]
        artifacts = snapshot.get("artifacts")
        blob_refs = dict(snapshot.get("blob_refs") or {})
        storage = dict(snapshot.get("storage") or {})

        if isinstance(artifacts, dict):
            snapshot["artifact_keys"] = sorted(artifacts.keys())
            if artifacts:
                blob_path = self.blob_dir_for(run_id) / "artifacts.json"
                self._atomic_write_json(blob_path, artifacts)
                blob_refs["artifacts"] = blob_path.relative_to(self.base.parent).as_posix()
                snapshot["artifacts"] = {}
                snapshot["final_summary"] = _short_summary({"artifacts": artifacts})
                storage["artifacts"] = "blob"
            else:
                snapshot.setdefault("final_summary", "")
                storage.setdefault("artifacts", "inline")
        else:
            snapshot["artifact_keys"] = []
            snapshot["artifacts"] = {}
            snapshot.setdefault("final_summary", "")
            storage.setdefault("artifacts", "inline")

        snapshot["blob_refs"] = blob_refs
        storage["index_version"] = "icr.hermes.storage.v1"
        snapshot["storage"] = storage
        return snapshot

    def _resolve_blobs(self, data: dict[str, Any]) -> dict[str, Any]:
        refs = data.get("blob_refs") or {}
        if not isinstance(refs, dict):
            return data
        artifact_ref = refs.get("artifacts")
        artifacts = data.get("artifacts")
        if artifact_ref and (not isinstance(artifacts, dict) or not artifacts):
            blob_path = self.base.parent / str(artifact_ref)
            if not blob_path.exists():
                raise FileNotFoundError(f"ICR artifact blob missing for {data.get('run_id')}: {blob_path}")
            blob = json.loads(blob_path.read_text(encoding="utf-8"))
            if not isinstance(blob, dict):
                raise ValueError(f"Invalid ICR artifact blob: {blob_path}")
            data["artifacts"] = blob
            data["artifact_keys"] = sorted(blob.keys())
        return data

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
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
                handle.write(dumps(data))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if tmp_name:
                try:
                    Path(tmp_name).unlink(missing_ok=True)
                except OSError:
                    pass

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
                    "artifact_keys": data.get("artifact_keys", []),
                    "checkpoint_count": len(data.get("checkpoints", [])),
                    "final_summary": data.get("final_summary") or _short_summary(data),
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
