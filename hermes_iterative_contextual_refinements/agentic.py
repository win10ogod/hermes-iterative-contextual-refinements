"""Agentic refinement engine with internal tool-loop semantics."""

from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from .config import ICRConfig
from .json_utils import utc_now_iso
from .llm import ICRLlm
from .schemas import AGENTIC_ORCHESTRATOR_SCHEMA
from .source_prompts import load_agentic_prompts


_AGENTIC_SOURCE_PROMPTS = load_agentic_prompts()
AGENTIC_SYSTEM_PROMPT = _AGENTIC_SOURCE_PROMPTS["agentic_system"]
VERIFIER_SYSTEM_PROMPT = _AGENTIC_SOURCE_PROMPTS["verifier_system"]

AGENTIC_TOOLS = [
    "read_current_content",
    "multi_edit",
    "searchacademia",
    "searchacademia_and",
    "verify_current_content",
    "Exit",
]


class AgenticRefinementEngine:
    def __init__(self, llm: ICRLlm, record: dict[str, Any], config: ICRConfig):
        self.llm = llm
        self.record = record
        self.config = config

    def run(self, initial_content: str, instruction: str = "") -> dict[str, Any]:
        state: dict[str, Any] = {
            "original_content": initial_content,
            "current_content": initial_content,
            "messages": [{"role": "user", "content": "Started agentic refinement run.", "timestamp": utc_now_iso()}],
            "content_history": [{"content": initial_content, "title": "Initial Content", "timestamp": utc_now_iso()}],
            "verifier_reports": [],
            "verification_count": 0,
            "last_verified_content": None,
            "is_complete": False,
            "tool_events": [],
        }
        for turn in range(1, self.config.agentic_max_tool_turns + 1):
            decision = self.llm.structured(
                role="agentic_orchestrator",
                purpose="agentic.orchestrator",
                instructions="Return JSON with assistant_text and tool_calls.",
                prompt=self._agent_prompt(state, instruction),
                schema=AGENTIC_ORCHESTRATOR_SCHEMA,
                system_prompt=AGENTIC_SYSTEM_PROMPT,
            )
            assistant_text = str(decision.get("assistant_text") or "")
            if assistant_text:
                state["messages"].append({"role": "agent", "content": assistant_text, "timestamp": utc_now_iso()})
            tool_calls = decision.get("tool_calls") or []
            if not tool_calls:
                continue
            for raw_call in tool_calls:
                name = str(raw_call.get("name"))
                args = raw_call.get("arguments") or {}
                result = self.execute_tool(state, name, args)
                state["tool_events"].append({"turn": turn, "tool": name, "arguments": args, "result": result})
                state["messages"].append({"role": "system", "content": result["content"], "status": result["status"], "timestamp": utc_now_iso()})
                if name == "Exit" and result["status"] == "success":
                    state["is_complete"] = True
                    self.record["artifacts"].update({"agentic_state": state, "final": {"final_content": state["current_content"]}})
                    return state
        raise RuntimeError("Agentic refinement reached max tool turns before verified Exit")

    def _agent_prompt(self, state: dict[str, Any], instruction: str) -> str:
        verified = state["last_verified_content"] == state["current_content"]
        return f"""Instruction:
{instruction or 'Refine the current working draft until it is verified and complete.'}

Available tools: {AGENTIC_TOOLS}

Current draft verification status: {'verified' if verified else 'not verified for latest state'}

Conversation/tool events:
{state['tool_events'][-8:]}

Return JSON:
{{"assistant_text":"brief visible note","tool_calls":[{{"name":"read_current_content","arguments":{{}}}}]}}"""

    def execute_tool(self, state: dict[str, Any], name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "read_current_content":
                return self._read_current_content(state, args)
            if name == "multi_edit":
                return self._multi_edit(state, args)
            if name == "searchacademia":
                query = str(args["query"]).strip()
                return self._tool_result(self._search_arxiv(query), "success")
            if name == "searchacademia_and":
                terms = [str(t).strip() for t in args["terms"] if str(t).strip()]
                query = " AND ".join(terms)
                return self._tool_result(self._search_arxiv(query, required_terms=terms), "success")
            if name == "verify_current_content":
                return self._verify_current_content(state)
            if name == "Exit":
                return self._exit(state)
            return self._tool_result(f"[TOOL_ERROR: Unknown tool type: {name}]", "error")
        except Exception as exc:
            return self._tool_result(f"[TOOL_ERROR: {type(exc).__name__}: {exc}]", "error")

    def _read_current_content(self, state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        start = args.get("startLine")
        end = args.get("endLine")
        if start is None and end is None:
            return self._tool_result(state["current_content"], "success")
        if start is None or end is None or int(end) < int(start):
            return self._tool_result("Provide both startLine and endLine, and ensure endLine is greater than or equal to startLine.", "error")
        lines = state["current_content"].split("\n")
        return self._tool_result("\n".join(lines[int(start) - 1 : int(end)]), "success")

    def _multi_edit(self, state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        operations = args.get("operations") or []
        if not operations:
            return self._tool_result("multi_edit requires at least one operation.", "error")
        current = state["current_content"]
        ok = 0
        fail = 0
        logs = []
        for op in operations:
            result = apply_operation(current, op)
            current = result["result"]
            if result["success"]:
                ok += 1
                logs.append(f"OK {op.get('action')}")
            else:
                fail += 1
                logs.append(f"FAIL {op.get('action')}: {result.get('error')}")
        changed = current != state["current_content"]
        if changed:
            state["current_content"] = current
            state["content_history"].append({"content": current, "title": f"After {ok} successful edits", "timestamp": utc_now_iso()})
            state["last_verified_content"] = None
        return self._tool_result("\n".join([f"Multi-edit finished: {ok} OK, {fail} FAIL", *logs]), "success")

    def _verify_current_content(self, state: dict[str, Any]) -> dict[str, Any]:
        report = self.llm.complete(
            role="agentic_verifier",
            purpose="agentic.verify_current_content",
            prompt=f"<current_content>\n{state['current_content']}\n</current_content>",
            system_prompt=VERIFIER_SYSTEM_PROMPT,
            temperature=0.2,
        ).strip()
        if not report:
            return self._tool_result("[VERIFIER_ERROR: Verifier returned an empty response]", "error")
        state["verifier_reports"].append(report)
        state["verification_count"] += 1
        state["last_verified_content"] = state["current_content"]
        return self._tool_result(report, "success")

    def _exit(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["last_verified_content"] != state["current_content"]:
            return self._tool_result("Exit rejected: verify the latest draft before finishing.", "error")
        return self._tool_result("Agent has completed the refinement process.", "success")

    def _search_arxiv(self, query: str, required_terms: list[str] | None = None) -> str:
        params = urllib.parse.urlencode({"search_query": f"all:{query}", "start": 0, "max_results": 10})
        url = f"https://export.arxiv.org/api/query?{params}"
        with urllib.request.urlopen(url, timeout=15) as response:
            raw = response.read()
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = []
        required = [term.lower() for term in (required_terms or [])]
        for entry in root.findall("atom:entry", ns):
            title = "".join(entry.findtext("atom:title", default="", namespaces=ns).split())
            summary = " ".join(entry.findtext("atom:summary", default="", namespaces=ns).split())
            text = f"{title} {summary}".lower()
            if required and not all(term.lower() in text for term in required):
                continue
            link = entry.findtext("atom:id", default="", namespaces=ns)
            entries.append(f"[Paper {len(entries) + 1}]\nTitle: {title}\nURL: {link}\nSummary: {summary}")
            if len(entries) >= 10:
                break
        return "\n" + "=" * 80 + "\n".join(entries) if entries else f"No papers found for query: {query}"

    def _tool_result(self, content: str, status: str) -> dict[str, str]:
        return {"content": content, "status": status}


def apply_operation(content: str, operation: dict[str, Any]) -> dict[str, Any]:
    action = operation.get("action")
    target = operation.get("target")
    replacement = operation.get("content")
    if not isinstance(target, str) or not target:
        return {"success": False, "result": content, "error": "operation target must be non-empty"}
    if action == "search_and_replace":
        if replacement is None:
            return {"success": False, "result": content, "error": "search_and_replace requires content"}
        if target not in content:
            return {"success": False, "result": content, "error": f"String not found: {target[:100]}"}
        return {"success": True, "result": content.replace(target, str(replacement), 1)}
    if action == "delete":
        if target not in content:
            return {"success": False, "result": content, "error": f"String not found: {target[:100]}"}
        return {"success": True, "result": content.replace(target, "", 1)}
    if action == "insert_before":
        if replacement is None:
            return {"success": False, "result": content, "error": "insert_before requires content"}
        index = content.find(target)
        if index == -1:
            return {"success": False, "result": content, "error": f"Marker not found: {target[:100]}"}
        return {"success": True, "result": content[:index] + str(replacement) + content[index:]}
    if action == "insert_after":
        if replacement is None:
            return {"success": False, "result": content, "error": "insert_after requires content"}
        index = content.find(target)
        if index == -1:
            return {"success": False, "result": content, "error": f"Marker not found: {target[:100]}"}
        return {"success": True, "result": content[: index + len(target)] + str(replacement) + content[index + len(target) :]}
    return {"success": False, "result": content, "error": f"Unknown edit action: {action}"}
