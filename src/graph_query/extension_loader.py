"""
Load **extension** graph tools from ``extension_registry.json`` and ``generated/*.py``.

Core tools live in ``tool_agent``; extensions are merged at runtime via
:func:`src.llm.tool_agent.refresh_graph_tools_with_extensions`.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable

_REGISTRY_PATH = Path(__file__).resolve().parent / "extension_registry.json"
_GENERATED_PKG = "src.graph_query.generated"


def registry_path() -> Path:
    return _REGISTRY_PATH


def read_registry_entries() -> list[dict[str, Any]]:
    if not _REGISTRY_PATH.is_file():
        return []
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def write_registry_entries(entries: list[dict[str, Any]]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def active_extension_specs() -> list[dict[str, Any]]:
    """Planner-shaped tool dicts for active registry rows."""
    out: list[dict[str, Any]] = []
    for e in read_registry_entries():
        if not e.get("active", True):
            continue
        name = str(e.get("name", "")).strip()
        desc = str(e.get("description", "")).strip()
        schema = e.get("input_schema")
        if not name or not isinstance(schema, dict):
            continue
        out.append(
            {
                "name": name,
                "description": desc or f"Extension graph tool `{name}` (registry).",
                "input_schema": schema,
            }
        )
    return out


def load_extension_handlers() -> dict[str, Callable[..., Any]]:
    """``tool_name`` → ``run(tool_input: dict) -> str`` (or any return coerced to str by caller)."""
    handlers: dict[str, Callable[..., Any]] = {}
    for e in read_registry_entries():
        if not e.get("active", True):
            continue
        name = str(e.get("name", "")).strip()
        mod = str(e.get("module") or name).strip()
        if not name or not mod:
            continue
        try:
            m = importlib.import_module(f"{_GENERATED_PKG}.{mod}")
            run = getattr(m, "run", None)
            if not callable(run):
                continue
            handlers[name] = run
        except Exception:
            continue
    return handlers


def reserved_tool_names() -> frozenset[str]:
    """Core tool names plus any registered extension names (no collisions)."""
    from src.llm import tool_agent as ta

    names = {t["name"] for t in ta._CORE_GRAPH_TOOLS}
    for e in read_registry_entries():
        n = str(e.get("name", "")).strip()
        if n:
            names.add(n)
    return frozenset(names)
