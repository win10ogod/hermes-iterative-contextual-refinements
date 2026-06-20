"""Hermes-side diagnostics for ICR plugin registration."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata as metadata
import json
import os
import sys
from typing import Any

from .constants import PLUGIN_NAME, PLUGIN_VERSION, TOOLSET_NAME

EXPECTED_TOOLS = {"icr_run", "icr_start", "icr_status", "icr_export", "icr_list_runs"}
BRIDGE_TOOLS = {"tool_search", "tool_describe", "tool_call"}


def diagnose(platform: str = "cli") -> dict[str, Any]:
    """Return a structured diagnosis of whether Hermes can expose ICR tools."""
    report: dict[str, Any] = {
        "plugin": PLUGIN_NAME,
        "expected_version": PLUGIN_VERSION,
        "platform": platform,
        "python": sys.executable,
        "cwd": os.getcwd(),
        "package": _package_report(),
        "entry_points": _entry_point_report(),
        "module": _module_report(),
        "hermes": {"available": False},
        "issues": [],
        "fixes": [],
    }
    _add_metadata_version_issue(report)

    hermes = report["hermes"]
    try:
        from hermes_cli.config import load_config
        from hermes_cli.plugins import discover_plugins, get_plugin_manager
        from hermes_cli.tools_config import _get_platform_tools
        from model_tools import get_tool_definitions
        from tools.registry import registry
    except Exception as exc:
        hermes["import_error"] = repr(exc)
        report["issues"].append("Hermes modules are not importable in this Python environment.")
        report["fixes"].append("Run this doctor with the same Python environment that launches Hermes.")
        _add_entry_point_fixes(report)
        return report

    hermes["available"] = True
    try:
        config = load_config()
    except Exception as exc:
        hermes["config_error"] = repr(exc)
        config = {}

    hermes["config"] = _config_summary(config, platform)

    try:
        discover_plugins(force=True)
        manager = get_plugin_manager()
        loaded = manager._plugins.get(PLUGIN_NAME)
        if loaded is None:
            hermes["loaded_plugin"] = None
            report["issues"].append("Hermes did not load the ICR plugin.")
            report["fixes"].append(f"Enable the plugin in config.yaml under plugins.enabled: {PLUGIN_NAME}")
        else:
            hermes["loaded_plugin"] = {
                "enabled": bool(getattr(loaded, "enabled", False)),
                "error": getattr(loaded, "error", None),
                "tools_registered": sorted(getattr(loaded, "tools_registered", []) or []),
                "commands_registered": sorted(getattr(loaded, "commands_registered", []) or []),
            }
            if getattr(loaded, "error", None):
                report["issues"].append(f"Hermes loaded the plugin with error: {loaded.error}")
            if not getattr(loaded, "enabled", False):
                report["issues"].append("Hermes discovered the plugin but did not enable it.")
    except Exception as exc:
        hermes["discovery_error"] = repr(exc)
        report["issues"].append("Hermes plugin discovery failed while checking ICR.")

    registry_tools = _registry_tools(registry)
    hermes["registry"] = registry_tools
    registered = set(registry_tools.get("icr_tools", {}))
    if not EXPECTED_TOOLS.issubset(registered):
        missing = sorted(EXPECTED_TOOLS - registered)
        report["issues"].append(f"ICR tools are missing from the Hermes registry: {', '.join(missing)}")

    try:
        enabled_toolsets = set(_get_platform_tools(config, platform, include_default_mcp_servers=False))
        hermes["enabled_toolsets"] = sorted(enabled_toolsets)
        if TOOLSET_NAME not in enabled_toolsets:
            report["issues"].append(f"The '{TOOLSET_NAME}' toolset is not enabled for platform '{platform}'.")
            report["fixes"].append(f"Run: hermes tools enable {TOOLSET_NAME} --platform {platform}")
            if platform == "cli":
                report["fixes"].append(f"Inside Hermes CLI, run: /tools enable {TOOLSET_NAME}")
    except Exception as exc:
        hermes["toolset_error"] = repr(exc)

    try:
        enabled = hermes.get("enabled_toolsets")
        definitions_report = _tool_definitions_report(get_tool_definitions, enabled)
        hermes["model_tool_definitions"] = definitions_report
        direct = set(definitions_report.get("direct_icr_tools", []))
        assembled = set(definitions_report.get("assembled_icr_tools", []))
        bridges = set(definitions_report.get("assembled_bridge_tools", []))
        if EXPECTED_TOOLS.issubset(direct) and not assembled and bridges:
            report["issues"].append("ICR tools are deferred behind Hermes tool_search bridge tools.")
            report["fixes"].append("Ask the agent to use tool_search for ICR, or set tools.tool_search.enabled: off.")
        elif EXPECTED_TOOLS.issubset(registered) and not direct:
            report["issues"].append("ICR tools are registered but filtered out of the model tool definitions.")
    except Exception as exc:
        hermes["model_tool_definitions_error"] = repr(exc)

    _add_entry_point_fixes(report)
    if not report["issues"]:
        report["ok"] = True
        report["summary"] = "ICR is registered and visible to the selected Hermes platform."
    else:
        report["ok"] = False
        report["fixes"] = _dedupe(report["fixes"])
    return report


def _package_report() -> dict[str, Any]:
    try:
        return {"installed_version": metadata.version(PLUGIN_NAME)}
    except Exception as exc:
        return {"installed_version": None, "error": repr(exc)}


def _entry_point_report() -> list[dict[str, Any]]:
    try:
        eps = metadata.entry_points()
        group_eps = eps.select(group="hermes_agent.plugins") if hasattr(eps, "select") else eps.get("hermes_agent.plugins", [])
    except Exception as exc:
        return [{"error": repr(exc)}]

    result = []
    for ep in group_eps:
        if ep.name != PLUGIN_NAME:
            continue
        item: dict[str, Any] = {"name": ep.name, "value": ep.value}
        try:
            loaded = ep.load()
            item["loaded_type"] = type(loaded).__name__
            item["has_register"] = hasattr(loaded, "register")
        except Exception as exc:
            item["load_error"] = repr(exc)
        result.append(item)
    return result


def _module_report() -> dict[str, Any]:
    try:
        module = importlib.import_module("hermes_iterative_contextual_refinements")
        return {
            "file": getattr(module, "__file__", None),
            "version": getattr(module, "__version__", None),
            "has_register": hasattr(module, "register"),
        }
    except Exception as exc:
        return {"error": repr(exc)}


def _config_summary(config: dict[str, Any], platform: str) -> dict[str, Any]:
    plugins = config.get("plugins") if isinstance(config, dict) else {}
    if not isinstance(plugins, dict):
        plugins = {}
    platform_toolsets = config.get("platform_toolsets") if isinstance(config, dict) else {}
    if not isinstance(platform_toolsets, dict):
        platform_toolsets = {}
    known = config.get("known_plugin_toolsets") if isinstance(config, dict) else {}
    if not isinstance(known, dict):
        known = {}
    agent = config.get("agent") if isinstance(config, dict) else {}
    if not isinstance(agent, dict):
        agent = {}
    tools = config.get("tools") if isinstance(config, dict) else {}
    if not isinstance(tools, dict):
        tools = {}
    return {
        "plugins_enabled": plugins.get("enabled", []),
        "platform_toolsets": platform_toolsets.get(platform),
        "known_plugin_toolsets": known.get(platform),
        "agent_disabled_toolsets": agent.get("disabled_toolsets", []),
        "tool_search": tools.get("tool_search"),
    }


def _registry_tools(registry: Any) -> dict[str, Any]:
    names = sorted(name for name in registry.get_all_tool_names() if name.startswith("icr_"))
    return {
        "icr_tools": {name: registry.get_toolset_for_tool(name) for name in names},
        "registered_toolsets": sorted(
            name for name in registry.get_registered_toolset_names() if name == TOOLSET_NAME
        ),
    }


def _tool_definitions_report(get_tool_definitions: Any, enabled_toolsets: list[str] | None) -> dict[str, Any]:
    direct_defs = get_tool_definitions(
        enabled_toolsets=enabled_toolsets,
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    assembled_defs = get_tool_definitions(
        enabled_toolsets=enabled_toolsets,
        quiet_mode=True,
        skip_tool_search_assembly=False,
    )
    direct_names = _definition_names(direct_defs)
    assembled_names = _definition_names(assembled_defs)
    return {
        "direct_icr_tools": sorted(name for name in direct_names if name.startswith("icr_")),
        "assembled_icr_tools": sorted(name for name in assembled_names if name.startswith("icr_")),
        "assembled_bridge_tools": sorted(name for name in assembled_names if name in BRIDGE_TOOLS),
        "direct_count": len(direct_names),
        "assembled_count": len(assembled_names),
    }


def _definition_names(defs: list[dict[str, Any]]) -> list[str]:
    return [
        name
        for item in defs
        for name in [item.get("function", {}).get("name")]
        if isinstance(name, str)
    ]


def _add_entry_point_fixes(report: dict[str, Any]) -> None:
    for item in report.get("entry_points", []):
        value = item.get("value")
        if value == "hermes_iterative_contextual_refinements:register" or item.get("loaded_type") == "function":
            report["issues"].append("The installed entry point is stale and points at register() instead of the plugin module.")
            report["fixes"].append("Reinstall the plugin with: python -m pip install -U -e .")
        if item.get("load_error"):
            report["issues"].append(f"The ICR entry point failed to load: {item['load_error']}")
            report["fixes"].append("Reinstall the plugin in the Python environment that launches Hermes.")
    if not report.get("entry_points"):
        report["fixes"].append("If using pip installation, run: python -m pip install -U -e .")


def _add_metadata_version_issue(report: dict[str, Any]) -> None:
    installed = report.get("package", {}).get("installed_version")
    module_version = report.get("module", {}).get("version")
    if installed and installed != PLUGIN_VERSION:
        report["issues"].append(
            f"Installed package metadata is {installed}, but this source expects {PLUGIN_VERSION}."
        )
        report["fixes"].append("Refresh editable metadata with: python -m pip install -U -e .")
    if module_version and module_version != PLUGIN_VERSION:
        report["issues"].append(
            f"Imported module version is {module_version}, but this source expects {PLUGIN_VERSION}."
        )
        report["fixes"].append("Ensure Hermes imports the updated repository path, then restart Hermes.")


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose Hermes ICR plugin registration.")
    parser.add_argument("--platform", default="cli", help="Hermes platform key to inspect, default: cli")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for explicit scripting; JSON is the default.")
    args = parser.parse_args(argv)
    print(json.dumps(diagnose(platform=args.platform), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
