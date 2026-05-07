"""
Generate **Neo4j-native** Python for a freshly authored registry extension (``native_ext_generated/<name>.py``).

Runs immediately after the NetworkX ``generated/<name>.py`` passes pytest so ``NEO4J_READ_MODE=native``
never executes NetworkX in extension ``run()``.
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from src.llm.json_extract import extract_json_object
from src.llm.prompts import SYSTEM_NATIVE_EXTENSION_AUTHOR, SYSTEM_NATIVE_EXTENSION_AUTHOR_OLLAMA


def _native_generated_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "graph_query" / "native_ext_generated"


_FORBIDDEN_NATIVE_NAMES = frozenset({"get_graph", "_require_graph"})


def _validate_native_extension_source(src: str) -> str | None:
    """Return error message or ``None`` if the native port source is acceptable."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return f"syntax: {exc}"

    allowed_import_from = frozenset(
        {
            "__future__",
            "src.graph_store.neo4j_read_session",
            "src.graph_query.neo4j_native_reads",
        }
    )
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
    has_run_native = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                full = alias.name or ""
                if "query_graph" in full:
                    return "disallowed import (use Cypher only): query_graph"
                base = full.split(".")[0]
                if base and base not in allowed_import_roots:
                    return f"disallowed import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if "query_graph" in mod:
                return f"disallowed from-import (use Cypher only): {mod}"
            if mod in allowed_import_from or mod == "__future__":
                continue
            base = mod.split(".")[0] if mod else ""
            if base == "src" and mod not in allowed_import_from:
                return f"disallowed from-import: {mod}"
            if base and base not in allowed_import_roots and base != "src":
                return f"disallowed from-import: {mod}"
        elif isinstance(node, ast.FunctionDef) and node.name == "run_native":
            has_run_native = True
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NATIVE_NAMES:
            return f"disallowed name (in-memory graph API): {node.id}"
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "nx":
                return "networkx (nx) is not allowed in native extension ports"

    if not has_run_native:
        return "missing def run_native(tool_input: dict[str, Any]) -> str"

    return None


def _call_author_llm_native(
    backend: str,
    client: Any,
    model_name: str,
    *,
    user_text: str,
) -> str:
    system = SYSTEM_NATIVE_EXTENSION_AUTHOR_OLLAMA if backend == "ollama" else SYSTEM_NATIVE_EXTENSION_AUTHOR
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


def _native_user_blob(
    tool_name: str,
    description: str,
    input_schema: dict[str, Any],
    question: str,
    preflight: dict[str, Any],
    networkx_body: str,
) -> str:
    parts = [
        f"TOOL_NAME: {tool_name}\n",
        f"DESCRIPTION:\n{description}\n",
        f"INPUT_SCHEMA:\n{json.dumps(input_schema, indent=2, ensure_ascii=False)}\n",
        f"ORIGINAL_USER_QUESTION:\n{question.strip()}\n",
        f"PREFLIGHT_JSON:\n{json.dumps(preflight, indent=2, ensure_ascii=False)}\n",
        "REFERENCE_NETWORKX_IMPLEMENTATION (same semantics; port to Cypher + rq()):\n",
        networkx_body,
        "\n\nProduce the native module JSON per system instructions.",
    ]
    return "".join(parts)


def try_author_native_extension(
    *,
    backend: str,
    client: Any,
    model_name: str,
    tool_name: str,
    description: str,
    input_schema: dict[str, Any],
    question: str,
    preflight: dict[str, Any],
    networkx_function_body: str,
) -> dict[str, Any]:
    """
    Write ``native_ext_generated/{tool_name}.py`` with ``run_native`` calling ``run_read_query``.

    Returns ``{"activated": True, ...}`` or ``{"activated": False, "error": ...}``.
    """
    user_text = _native_user_blob(
        tool_name,
        description,
        input_schema,
        question,
        preflight,
        networkx_function_body,
    )
    raw = _call_author_llm_native(backend, client, model_name, user_text=user_text)
    data = extract_json_object(raw) or {}
    if not isinstance(data, dict):
        return {"activated": False, "error": "native_author_invalid_json", "raw_preview": raw[:2000]}

    module_src = str(data.get("module_source", "")).strip()
    if not module_src:
        return {"activated": False, "error": "missing_module_source", "raw_preview": raw[:1200]}

    err = _validate_native_extension_source(module_src)
    if err:
        return {"activated": False, "error": f"native_validation:{err}", "raw_preview": module_src[:2000]}

    gen_dir = _native_generated_dir()
    gen_dir.mkdir(parents=True, exist_ok=True)
    path = gen_dir / f"{tool_name}.py"

    try:
        path.write_text(module_src, encoding="utf-8")
        compile(module_src, str(path), "exec")
    except Exception as exc:
        path.unlink(missing_ok=True)
        return {"activated": False, "error": f"native_write_or_compile:{exc}"}

    mod_path = f"src.graph_query.native_ext_generated.{tool_name}"
    if mod_path in sys.modules:
        del sys.modules[mod_path]
    try:
        importlib.import_module(mod_path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        return {"activated": False, "error": f"native_import_failed:{exc}"}

    from src.graph_query.neo4j_native_extensions import clear_dynamic_native_cache

    clear_dynamic_native_cache()

    return {
        "activated": True,
        "native_module_path": str(path),
    }
