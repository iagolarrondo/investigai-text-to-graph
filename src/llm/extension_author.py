"""
LLM-authored **extension tools**: write ``generated/<name>.py``, validate, run pytest smoke, then registry.

Gated by ``INVESTIGATION_EXTENSION_AUTHORING`` (see ``.env.example``).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.graph_query.extension_loader import (
    read_registry_entries,
    registry_path,
    reserved_tool_names,
    write_registry_entries,
)
from src.llm.json_extract import extract_json_object
from src.llm.prompts import SYSTEM_TOOL_EXTENSION_AUTHOR, SYSTEM_TOOL_EXTENSION_AUTHOR_OLLAMA


def extension_authoring_enabled() -> bool:
    v = (os.environ.get("INVESTIGATION_EXTENSION_AUTHORING") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _generated_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "graph_query" / "generated"


def _sanitize_tool_name(raw: str) -> str | None:
    s = (raw or "").strip().lower()
    if not re.match(r"^[a-z][a-z0-9_]{1,62}$", s):
        return None
    if s in ("run", "json", "get_graph", "generated", "src"):
        return None
    if s in reserved_tool_names():
        return None
    return s


_MODULE_TEMPLATE = '''\
"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
{body}
'''


_FORBIDDEN_CALL_IDS = frozenset(
    {"eval", "exec", "open", "compile", "__import__", "breakpoint", "input"}
)


def _validate_extension_source(src: str) -> str | None:
    """Return error message or None if acceptable."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return f"syntax: {exc}"

    allowed_import_roots = frozenset(
        {
            "json",
            "typing",
            "collections",
            "itertools",
            "math",
            "re",
            "functools",
            "operator",
            "datetime",
            "decimal",
        }
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = (alias.name or "").split(".")[0]
                if base and base not in allowed_import_roots:
                    return f"disallowed import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "src.graph_query.query_graph":
                continue
            # Template (and valid extensions) use ``from __future__ import annotations``.
            if mod == "__future__":
                continue
            base = mod.split(".")[0] if mod else ""
            if base == "src":
                return f"disallowed from-import: {mod}"
            if base and base not in allowed_import_roots:
                return f"disallowed from-import: {mod}"
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _FORBIDDEN_CALL_IDS:
                return f"disallowed call: {fn.id}"
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.attr in _FORBIDDEN_CALL_IDS:
                    return f"disallowed call: {fn.attr}"
    return None


def _author_user_blob(question: str, preflight: dict[str, Any], catalog_json: str) -> str:
    parts = [
        f"USER_QUESTION:\n{question.strip()}\n",
        f"PREFLIGHT_JSON:\n{json.dumps(preflight, indent=2, ensure_ascii=False)}\n",
        "EXISTING_TOOL_CATALOG (name + short description):\n",
        catalog_json,
        "\n\nAuthor ONE new tool as specified in your system instructions. "
        "Prefer a tight implementation using get_graph() and standard patterns.",
    ]
    return "".join(parts)


def _call_author_llm(backend: str, client: Any, model_name: str, *, system: str, user_text: str) -> str:
    if backend == "ollama":
        from src.llm.local_ollama import ollama_generate_text

        return ollama_generate_text(
            client,
            model=model_name,
            system_instruction=system,
            user_text=user_text,
            num_predict=8192,
            json_mode=True,
        )
    if backend == "anthropic":
        from src.llm.anthropic_llm import anthropic_generate_text

        return anthropic_generate_text(
            client,
            model=model_name,
            system_instruction=system,
            user_text=user_text,
            max_tokens=8192,
        )
    from src.llm.gemini_llm import generate_text

    return generate_text(
        client,
        model=model_name,
        system_instruction=system,
        user_text=user_text,
        max_output_tokens=8192,
    )


def try_author_extension(
    *,
    backend: str,
    client: Any,
    model_name: str,
    question: str,
    preflight: dict[str, Any],
    tool_catalog_json: str,
) -> dict[str, Any]:
    """
    Attempt to add a new tool module + registry row. Returns a dict suitable for ``ToolAgentResult.extension_authoring``.
    """
    if not extension_authoring_enabled():
        return {"activated": False, "skipped": "INVESTIGATION_EXTENSION_AUTHORING not enabled"}

    system = (
        SYSTEM_TOOL_EXTENSION_AUTHOR_OLLAMA if backend == "ollama" else SYSTEM_TOOL_EXTENSION_AUTHOR
    )
    raw = _call_author_llm(
        backend,
        client,
        model_name,
        system=system,
        user_text=_author_user_blob(question, preflight, tool_catalog_json),
    )
    data = extract_json_object(raw) or {}
    if not isinstance(data, dict):
        return {"activated": False, "error": "author_llm_invalid_json", "raw_preview": raw[:2000]}

    tool_name = _sanitize_tool_name(str(data.get("tool_name", "")))
    if not tool_name:
        return {"activated": False, "error": "invalid_or_reserved_tool_name", "raw_preview": raw[:1200]}

    description = str(data.get("description", "")).strip()
    input_schema = data.get("input_schema")
    function_body = str(data.get("function_body", "")).rstrip()
    if not description or not isinstance(input_schema, dict) or not function_body.strip():
        return {"activated": False, "error": "missing_description_schema_or_body"}

    body = textwrap.indent(textwrap.dedent(function_body), "    ")
    full_src = _MODULE_TEMPLATE.format(body=body)
    err = _validate_extension_source(full_src)
    if err:
        return {"activated": False, "error": f"validation_failed:{err}"}

    gen_dir = _generated_dir()
    gen_dir.mkdir(parents=True, exist_ok=True)
    path = gen_dir / f"{tool_name}.py"
    if path.is_file():
        return {"activated": False, "error": f"module_file_already_exists:{tool_name}"}

    try:
        path.write_text(full_src, encoding="utf-8")
        compile(full_src, str(path), "exec")
    except Exception as exc:
        if path.is_file():
            path.unlink(missing_ok=True)
        return {"activated": False, "error": f"write_or_compile:{exc}"}

    entry = {
        "name": tool_name,
        "module": tool_name,
        "description": description,
        "input_schema": input_schema,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    prior = read_registry_entries()
    try:
        write_registry_entries(prior + [entry])
    except OSError as exc:
        path.unlink(missing_ok=True)
        return {"activated": False, "error": f"registry_write:{exc}"}

    root = _repo_root()
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_graph_extensions_smoke.py",
        "-q",
        "--tb=no",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        write_registry_entries(prior)
        path.unlink(missing_ok=True)
        return {"activated": False, "error": "pytest_timeout"}

    if proc.returncode != 0:
        write_registry_entries(prior)
        path.unlink(missing_ok=True)
        tail = (proc.stdout + "\n" + proc.stderr).strip()[-4000:]
        return {"activated": False, "error": "pytest_failed", "pytest_tail": tail}

    return {
        "activated": True,
        "tool_name": tool_name,
        "registry_path": str(registry_path()),
        "module_path": str(path),
    }
