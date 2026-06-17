"""Persistent Python execution sessions for Python-enabled ICR agents."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .constants import PLUGIN_NAME


_FENCE_RE = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_XML_RE = re.compile(r"<python>\s*(.*?)\s*</python>", re.IGNORECASE | re.DOTALL)

_WORKER = r'''
import contextlib
import io
import json
import traceback
import sys

ns = {"__name__": "__icr_python_session__"}

for line in sys.stdin:
    try:
        payload = json.loads(line)
        code = payload.get("code") or ""
        stdout = io.StringIO()
        stderr = io.StringIO()
        ok = True
        error = ""
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                exec(compile(code, "<icr-python>", "exec"), ns, ns)
            except BaseException:
                ok = False
                error = traceback.format_exc()
        print(json.dumps({
            "ok": ok,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "error": error,
        }, ensure_ascii=False), flush=True)
    except BaseException:
        print(json.dumps({
            "ok": False,
            "stdout": "",
            "stderr": "",
            "error": traceback.format_exc(),
        }, ensure_ascii=False), flush=True)
'''


def extract_python_blocks(text: str) -> list[str]:
    blocks = [m.group(1).strip() for m in _FENCE_RE.finditer(text or "")]
    blocks.extend(m.group(1).strip() for m in _XML_RE.finditer(text or ""))
    return [block for block in blocks if block]


class PythonSession:
    def __init__(self, workdir: Path, timeout_seconds: float):
        self.workdir = workdir
        self.timeout_seconds = timeout_seconds
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc and proc.poll() is None:
            proc.kill()

    def execute(self, code: str) -> dict[str, Any]:
        with self._lock:
            proc = self._ensure_process()
            assert proc.stdin is not None
            assert proc.stdout is not None
            proc.stdin.write(json.dumps({"code": code}, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            line = self._readline_with_timeout(proc)
            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                return {"ok": False, "stdout": "", "stderr": "", "error": f"Invalid worker response: {exc}: {line[:500]}"}

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-c", _WORKER],
            cwd=str(self.workdir),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        return self._proc

    def _readline_with_timeout(self, proc: subprocess.Popen[str]) -> str:
        result: list[str] = []
        error: list[BaseException] = []

        def reader() -> None:
            try:
                assert proc.stdout is not None
                result.append(proc.stdout.readline())
            except BaseException as exc:  # pragma: no cover - defensive
                error.append(exc)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(self.timeout_seconds)
        if thread.is_alive():
            self.close()
            raise TimeoutError(f"Python execution exceeded {self.timeout_seconds:g}s")
        if error:
            raise RuntimeError(str(error[0]))
        if not result or result[0] == "":
            stderr = ""
            try:
                if proc.stderr is not None:
                    stderr = proc.stderr.read()
            except Exception:
                pass
            raise RuntimeError(f"Python worker exited without response. stderr={stderr[:500]}")
        return result[0]


class PythonExecutionManager:
    def __init__(self, record: dict[str, Any], timeout_seconds: float):
        self.record = record
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        self._sessions: dict[str, PythonSession] = {}

    def execute_blocks(self, *, role: str, blocks: list[str]) -> list[dict[str, Any]]:
        outputs = []
        session = self._session(role)
        for index, code in enumerate(blocks, 1):
            try:
                result = session.execute(code)
            except BaseException as exc:
                result = {"ok": False, "stdout": "", "stderr": "", "error": f"{type(exc).__name__}: {exc}"}
            entry = {"role": role, "index": index, "code": code, **result}
            outputs.append(entry)
        with self._lock:
            self.record.setdefault("python_executions", []).extend(outputs)
        return outputs

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()

    def _session(self, role: str) -> PythonSession:
        with self._lock:
            if role not in self._sessions:
                root = self._python_root() / _safe(self.record["run_id"]) / _safe(role)
                self._sessions[role] = PythonSession(root, self.timeout_seconds)
            return self._sessions[role]

    def _python_root(self) -> Path:
        try:
            from hermes_constants import get_hermes_home

            return get_hermes_home() / "icr" / "python"
        except Exception:
            return Path.home() / ".hermes" / "icr" / "python"


def format_python_results(results: list[dict[str, Any]]) -> str:
    parts = []
    for result in results:
        parts.append(
            "\n".join(
                [
                    f"<PythonExecution role=\"{result.get('role')}\" index=\"{result.get('index')}\" ok=\"{str(result.get('ok')).lower()}\">",
                    "<Code>",
                    str(result.get("code", "")),
                    "</Code>",
                    "<Stdout>",
                    str(result.get("stdout", "")),
                    "</Stdout>",
                    "<Stderr>",
                    str(result.get("stderr", "")),
                    "</Stderr>",
                    "<Error>",
                    str(result.get("error", "")),
                    "</Error>",
                    "</PythonExecution>",
                ]
            )
        )
    return "\n\n".join(parts)


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value)[:120] or PLUGIN_NAME
