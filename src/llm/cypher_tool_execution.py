"""
Execute a **named graph tool** by asking the investigation LLM to emit **read-only Cypher**.

Used when ``NEO4J_READ_MODE=llm_cypher``. The planner still picks the same tool names; this layer
replaces the hand-written ``neo4j_native_*`` Python implementations (and **extension** ``generated``
tools) with **model-generated** queries against ``:Entity`` / ``:GRAPH_EDGE`` (see ``sync_processed``).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from src.graph_query.cypher_read_guard import (
    extract_cypher_from_model_output,
    parse_cypher_json_payload,
    validate_read_only_cypher,
)
from src.graph_store.neo4j_read_session import run_read_query


def _investigation_llm_backend() -> str:
    v = (os.environ.get("INVESTIGATION_LLM") or "gemini").strip().lower()
    if v in ("ollama", "local"):
        return "ollama"
    if v in ("anthropic", "claude"):
        return "anthropic"
    return "gemini"


_SYSTEM_CYPHER_TOOL = """You turn a **single graph-tool invocation** into **one read-only Cypher** query for Neo4j.

## Graph schema (investigation extract)
- Nodes: ``(:Entity {node_id, node_type, label, source_table, properties_json})``
- Edges: ``(:Entity)-[r:GRAPH_EDGE {edge_id, edge_type, source_table, properties_json}]->(:Entity)``
- ``properties_json`` is a JSON **string** on the node/rel; filter with ``toString(n.properties_json) CONTAINS ...`` or match on ``label`` / ``node_id`` / ``node_type`` / ``edge_type``.

## Rules
- Output **only** a JSON object (no markdown, no prose): ``{"cypher": "<one statement>", "params": {...}}``.
- **Read-only**: ``MATCH``, ``OPTIONAL MATCH``, ``WITH``, ``WHERE``, ``RETURN``, ``ORDER BY``, ``LIMIT``, ``SKIP``, ``UNWIND``, ``DISTINCT``, ``UNION`` (if needed). No ``CREATE``, ``MERGE``, ``DELETE``, ``SET``, ``REMOVE``, ``CALL``, etc.
- One statement only; no semicolons inside except trailing is discouraged — **no** multi-statements.
- Prefer **parameters** for literals ($person_id, $q, …) and put values in ``params`` — do **not** concatenate user strings into the query unsafely without parameters.
- Add a **LIMIT** on open-ended listing (default cap 200 unless the tool implies fewer).
- Mirror the **intent** of the named tool from the bundled InvestigAI app (summaries, catalogs, neighbor lists, pattern helpers). Return rich columns the planner can read (ids, types, labels, counts, paths as lists of ids when helpful).

If the tool is unknown, still return a harmless query: ``MATCH (n:Entity) RETURN count(n) AS num_nodes LIMIT 1`` with empty params.
"""


def _llm_json_for_cypher(user_block: str) -> str:
    backend = _investigation_llm_backend()
    if backend == "anthropic":
        from anthropic import Anthropic

        from src.llm.anthropic_llm import anthropic_generate_text

        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        model = (os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6").strip()
        client = Anthropic(api_key=api_key)
        return anthropic_generate_text(
            client,
            model=model,
            system_instruction=_SYSTEM_CYPHER_TOOL,
            user_text=user_block,
            max_tokens=4096,
        )
    if backend == "ollama":
        from ollama import Client

        from src.llm.local_ollama import ollama_generate_text

        host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
        model = (os.environ.get("OLLAMA_MODEL") or "llama3.1").strip()
        client = Client(host=host)
        return ollama_generate_text(
            client,
            model=model,
            system_instruction=_SYSTEM_CYPHER_TOOL,
            user_text=user_block,
            num_predict=4096,
            json_mode=True,
        )
    from google import genai

    from src.llm.gemini_llm import generate_text

    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set.")
    model = (os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    client = genai.Client(api_key=api_key)
    return generate_text(
        client,
        model=model,
        system_instruction=_SYSTEM_CYPHER_TOOL,
        user_text=user_block,
        max_output_tokens=4096,
    )


def _normalize_tool_arguments(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Apply the same id normalizations as ``tool_agent._execute_graph_tool_raw``."""
    from src.graph_query import query_graph as qg
    from src.llm import tool_agent as ta

    inp = dict(tool_input)
    if name == "search_nodes":
        lim = int(inp.get("limit") or 40)
        inp["limit"] = min(max(lim, 1), 200)
        nt = inp.get("node_type")
        if isinstance(nt, str) and not nt.strip():
            inp["node_type"] = None
    elif name == "get_neighbors":
        nid = str(inp.get("node_id", "")).strip()
        if "|" not in nid and re.search(r"(?i)claim", nid):
            try:
                _G = qg.get_graph()
                if nid not in _G:
                    nid = ta.normalize_claim_node_id(nid)
            except RuntimeError:
                nid = ta.normalize_claim_node_id(nid)
        inp["node_id"] = nid
    elif name in ("get_person_policies", "policies_with_related_coparties", "get_person_subgraph_summary"):
        inp["person_node_id"] = ta.normalize_person_node_id(str(inp.get("person_node_id", "")))
    elif name in ("get_claim_network", "get_claim_subgraph_summary"):
        inp["claim_node_id"] = ta.normalize_claim_node_id(str(inp.get("claim_node_id", "")))
    elif name == "get_policy_network":
        inp["policy_node_id"] = ta.normalize_policy_node_id(str(inp.get("policy_node_id", "")))
    if name == "get_claim_subgraph_summary":
        depth = int(inp.get("max_depth") or 3)
        inp["max_depth"] = max(1, min(depth, 8))
    elif name == "get_person_subgraph_summary":
        depth = int(inp.get("max_depth") or 2)
        inp["max_depth"] = max(1, min(depth, 8))
    return {"tool": name, "arguments": inp}


def execute_extension_via_llm_cypher(name: str, tool_input: dict[str, Any]) -> str:
    """
    Run a **registry extension** tool by synthesizing Cypher from the extension's description + arguments.

    Uses ``extension_registry.json`` metadata so the model knows the tool's purpose and parameter schema.
    """
    try:
        from src.graph_query.extension_loader import read_registry_entries

        meta: dict[str, Any] | None = None
        for e in read_registry_entries():
            if not e.get("active", True):
                continue
            if str(e.get("name", "")).strip() == name:
                meta = e
                break
        if meta is None:
            return f"ERROR: Extension `{name}` not found in registry or inactive."

        payload = {
            "extension_tool": name,
            "description": str(meta.get("description", "")).strip(),
            "input_schema": meta.get("input_schema") or {},
            "arguments": dict(tool_input),
        }
        user_block = (
            "This is an **extension** graph tool (registry — not a core built-in). "
            "Infer the investigator intent from **description** and **arguments**, then output "
            "one read-only Cypher query that returns rows the planner can use (columns with clear names).\n\n"
            "EXTENSION_INVOCATION:\n"
            + json.dumps(payload, indent=2, default=str)
        )
        raw = _llm_json_for_cypher(user_block)
        try:
            cypher, params = parse_cypher_json_payload(raw)
        except ValueError:
            cypher = extract_cypher_from_model_output(raw)
            params = {}
        validate_read_only_cypher(cypher)
        rows = run_read_query(cypher, params)
        cap = 2000
        if len(rows) > cap:
            rows = rows[:cap] + [{"_truncated": True, "_note": f"first {cap} row(s) only"}]
        return json.dumps(rows, indent=2, default=str)
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"


def execute_tool_via_llm_cypher(name: str, tool_input: dict[str, Any]) -> str:
    """
    Run **one** tool by synthesizing Cypher via the configured investigation LLM.

    Returns JSON text (rows) or an ``ERROR:`` line on failure — same general contract as
    :func:`src.llm.tool_agent._execute_graph_tool_raw`.
    """
    try:
        spec = _normalize_tool_arguments(name, tool_input)
        user_block = (
            "Produce the JSON object now.\n\nTOOL_INVOCATION:\n"
            + json.dumps(spec, indent=2, default=str)
        )
        raw = _llm_json_for_cypher(user_block)
        try:
            cypher, params = parse_cypher_json_payload(raw)
        except ValueError:
            cypher = extract_cypher_from_model_output(raw)
            params = {}
        validate_read_only_cypher(cypher)
        rows = run_read_query(cypher, params)
        cap = 2000
        if len(rows) > cap:
            rows = rows[:cap] + [{"_truncated": True, "_note": f"first {cap} row(s) only"}]
        return json.dumps(rows, indent=2, default=str)
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"
