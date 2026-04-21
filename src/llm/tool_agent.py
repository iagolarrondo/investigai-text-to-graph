"""
**Tool-planner:** LLM function calling into ``query_graph`` helpers (**Gemini**, **Anthropic Claude**, or **local Ollama**).

The Streamlit entrypoint uses :func:`run_tool_planner_agent`, which delegates to
:func:`src.llm.orchestration.run_investigation_orchestrator` (planner ↔ judge → synthesis).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

try:
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

import pandas as pd

from src.graph_query import query_graph as qg
from src.llm.prompts import SYSTEM_TOOL_AGENT
from src.llm.result_serialize import investigation_payload_to_text

MAX_TOOL_CHARS = 14_000
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
# Default must be a **current** Claude API id (see Anthropic “All models”); older ids return 404.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def investigation_llm_backend() -> str:
    """``gemini`` (default), ``anthropic`` (Claude), or ``ollama`` (local). ``local`` → Ollama; ``claude`` → Anthropic."""
    v = (os.environ.get("INVESTIGATION_LLM") or "gemini").strip().lower()
    if v in ("ollama", "local"):
        return "ollama"
    if v in ("anthropic", "claude"):
        return "anthropic"
    return "gemini"


def normalize_person_node_id(raw: str) -> str:
    """
    Coerce ``1004``, ``person 1004`` → ``Person|1004`` when no pipe id is given.
    """
    s = (raw or "").strip()
    if not s:
        return s
    if "|" in s:
        return s
    if s.isdigit():
        return f"Person|{s}"
    m = re.search(r"(?i)person\D+(\d+)", s)
    if m:
        return f"Person|{m.group(1)}"
    return s


def normalize_policy_node_id(raw: str) -> str:
    """
    Coerce ``POL001`` → ``Policy|POL001`` when no pipe id is given (matches demo ids).
    """
    s = (raw or "").strip()
    if not s:
        return s
    if "|" in s:
        return s
    if re.match(r"^POL\d+$", s, re.IGNORECASE):
        return f"Policy|{s.upper()}"
    return s


def _append_claim_pipe_variants(token: str, out: list[str]) -> None:
    """Push canonical ``Claim|…`` guesses for a token (e.g. ``005``, ``C005``)."""
    t = (token or "").strip()
    if not t:
        return

    def add(x: str) -> None:
        if x and x not in out:
            out.append(x)

    if re.match(r"(?i)^C\d+$", t):
        add("Claim|" + t[0].upper() + t[1:])
        return
    if t.isdigit():
        add("Claim|C" + t.zfill(3))
        return
    add("Claim|" + t)


def claim_node_id_candidates(raw: str) -> list[str]:
    """
    Ordered candidate ids for fuzzy claim references (``Claim 005``, ``claim_C005``, ``C005``).

    The first candidate that exists as a **Claim** node in the loaded graph is used by
    :func:`normalize_claim_node_id`.
    """
    s = (raw or "").strip()
    if not s:
        return []
    if "|" in s:
        return [s]
    out: list[str] = []
    s_ns = re.sub(r"\s+", "", s)

    m = re.match(r"(?i)^claim_([A-Za-z0-9]+)$", s_ns)
    if m:
        _append_claim_pipe_variants(m.group(1), out)
    m2 = re.match(r"(?i)^claim[\s_-]+([A-Za-z0-9]+)\s*$", s)
    if m2:
        _append_claim_pipe_variants(m2.group(1), out)
    if re.match(r"(?i)^C\d+$", s_ns):
        _append_claim_pipe_variants(s_ns, out)
    if s_ns.isdigit():
        _append_claim_pipe_variants(s_ns, out)
    if not out:
        _append_claim_pipe_variants(s_ns, out)
    return out


def normalize_claim_node_id(raw: str) -> str:
    """
    Map human / model claim references to graph ``Claim|…`` node ids.

    Accepts e.g. ``Claim|C005``, ``claim_C005``, ``Claim 005``, ``C005``, ``005`` (demo CSVs
    use ``Claim|C00n``). When the graph is loaded, picks the first candidate that exists as a
    Claim node; otherwise returns the first candidate (caller may still get KeyError).
    """
    cands = claim_node_id_candidates(raw)
    if not cands:
        return (raw or "").strip()
    try:
        G = qg.get_graph()
    except RuntimeError:
        return cands[0]
    for c in cands:
        if c in G.nodes and G.nodes[c].get("node_type") == "Claim":
            return c
    return cands[0]


# Tool definitions (JSON Schema subset; used by the Gemini planner)
GRAPH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "summarize_graph",
        "description": (
            "Graph health summary: node/edge counts and frequency tables for node_type "
            "and edge_type. Use when the user asks what is in the graph or for orientation."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_graph_relationship_catalog",
        "description": (
            "**Future-proof schema introspection:** lists every directed triple "
            "(from_node_type, edge_type, to_node_type) with counts in the **current** CSVs. "
            "Use this when the question does not map to a named composite tool—so you can see "
            "how entity types connect and plan multi-step calls (search_nodes → get_neighbors → …). "
            "Updates automatically when the graph export changes; no new code required per question."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_nodes",
        "description": (
            "Find candidate node_ids by substring match on labels and properties. "
            "Use when the user gives a person name, policy number fragment, or unclear id. "
            "Optionally filter by node_type (e.g. Person, Claim, Policy)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Case-insensitive substring to search for.",
                },
                "node_type": {
                    "type": "string",
                    "description": "Optional: Person, Claim, Policy, BankAccount, Business, Address, …",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max matches to return (default 40, max 200).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_neighbors",
        "description": (
            "Directed neighbors of a node: outgoing (successors) and incoming (predecessors) ids. "
            "Use to explore connectivity from a known node_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "Exact graph node id."},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "get_person_policies",
        "description": (
            "List all policies linked to a Person via IS_COVERED_BY or SOLD_POLICY (person-centric). "
            "Use for questions like ‘policies for this individual’ or ‘what policies is Maria on’. "
            "Requires an exact Person node_id (use search_nodes first if needed)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_node_id": {
                    "type": "string",
                    "description": "Person node id, e.g. Person|1001, person_5001, or 1004 (normalized to Person|1004).",
                },
            },
            "required": ["person_node_id"],
        },
    },
    {
        "name": "policies_with_related_coparties",
        "description": (
            "Policies where the anchor person has IS_COVERED_BY/SOLD_POLICY AND another person "
            "on the **same** policy has a direct person→person tie with them (spouse, related-to, "
            "POA/HIPAA/diagnosing, same types as family clusters). Use for: ‘on a policy with someone "
            "they know’, ‘policy overlap with a relative’, ‘related party on same policy’ — **not** a claim query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_node_id": {
                    "type": "string",
                    "description": "Anchor Person id (Person|… or numeric id).",
                },
            },
            "required": ["person_node_id"],
        },
    },
    {
        "name": "get_claim_network",
        "description": (
            "Claim-centric slice: claim → policy, other claims on same policy, **people linked to the "
            "claim** (direct edges and via non-policy entities like eligibility review/care), **people "
            "on the policy** (insured/agent), claimant name match. Anchored on ONE claim. Not for "
            "‘all policies of a person’—use get_person_policies instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_node_id": {
                    "type": "string",
                    "description": (
                        "Claim id: canonical ``Claim|C005``, or ``claim_C005`` / ``Claim 005`` / ``C005`` "
                        "(normalized to graph node ids)."
                    ),
                },
            },
            "required": ["claim_node_id"],
        },
    },
    {
        "name": "get_claim_subgraph_summary",
        "description": (
            "Undirected N-hop neighborhood around a claim (any relationship types). "
            "Broader than get_claim_network."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_node_id": {
                    "type": "string",
                    "description": (
                        "Claim id: ``Claim|C005`` or fuzzy forms like ``claim_C005``, ``Claim 005`` (normalized)."
                    ),
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Hop radius (1–6 typical; default 3).",
                },
            },
            "required": ["claim_node_id"],
        },
    },
    {
        "name": "get_person_subgraph_summary",
        "description": (
            "Undirected N-hop neighborhood around a **Person** (any relationship types). "
            "Use for ‘what is around this insured/party’ without starting from a claim. "
            "Not for claim-centric questions—use get_claim_subgraph_summary with a Claim id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_node_id": {
                    "type": "string",
                    "description": "Person node id (Person|… or numeric; normalized like get_person_policies).",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Hop radius (1–6 typical; default 2).",
                },
            },
            "required": ["person_node_id"],
        },
    },
    {
        "name": "get_policy_network",
        "description": (
            "Policy-centric slice: the policy row, every Person on it (IS_COVERED_BY / SOLD_POLICY), "
            "and every Claim filed against it (IS_CLAIM_AGAINST_POLICY). Use when the anchor is a **policy** "
            "or policy number, not a claim. Complements get_claim_network (claim-first) and get_person_policies (person-first)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_node_id": {
                    "type": "string",
                    "description": "Policy node id, e.g. Policy|POL001 or POL001 (normalized).",
                },
            },
            "required": ["policy_node_id"],
        },
    },
    {
        "name": "find_shared_bank_accounts",
        "description": (
            "Bank accounts with two or more holders; addresses compared. Global graph query, no anchor."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "find_related_people_clusters",
        "description": (
            "Person–person connected components (family/social clusters). Global query."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "find_business_connection_patterns",
        "description": (
            "Business and person colocation at the same address. Global query."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _truncate(s: str, limit: int = MAX_TOOL_CHARS) -> str:
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[: limit - 80] + "\n\n…(truncated for context)…"


def _format_tool_payload(payload: dict[str, Any], *, truncate: bool = True) -> str:
    """Turn a query_graph return dict into readable text for the model or judge."""
    lines: list[str] = []
    if payload.get("summary"):
        lines.append(f"summary: {payload['summary']}")
    if payload.get("explanation_plain"):
        lines.append(f"explanation_plain:\n{payload['explanation_plain']}")
    if payload.get("evidence_bullets"):
        eb = payload["evidence_bullets"]
        if isinstance(eb, list):
            cap = 60 if truncate else len(eb)
            lines.append("evidence_bullets:\n" + "\n".join(f"- {b}" for b in eb[:cap]))
    for meta in (
        "person_node_id",
        "claim_node_id",
        "policy_node_id",
        "max_depth",
        "query",
        "node_type_filter",
    ):
        if payload.get(meta) is not None:
            lines.append(f"{meta}: {payload[meta]}")

    if "claim" in payload and isinstance(payload.get("claim"), pd.DataFrame):
        lines.append(investigation_payload_to_text("claim_network", payload))
    elif "policies" in payload:
        lines.append(investigation_payload_to_text("person_policies", payload))
    elif "matches" in payload:
        lines.append(investigation_payload_to_text("search_nodes", payload))
    elif "people_on_policy" in payload and "claims_on_policy" in payload:
        lines.append(investigation_payload_to_text("policy_network", payload))
    elif "nodes" in payload and "edges" in payload:
        if payload.get("person_node_id"):
            lines.append(investigation_payload_to_text("person_subgraph", payload))
        else:
            lines.append(investigation_payload_to_text("claim_subgraph", payload))
    elif "table" in payload and isinstance(payload.get("table"), pd.DataFrame):
        lines.append(investigation_payload_to_text("shared_bank", payload))
    text = "\n\n".join(lines)
    return _truncate(text) if truncate else text


def _execute_graph_tool_raw(name: str, tool_input: dict[str, Any]) -> str:
    """Run one tool; return full text before context-window truncation."""
    try:
        if name == "summarize_graph":
            out = qg.summarize_graph()
            return json.dumps(out, indent=2, default=str)

        if name == "get_graph_relationship_catalog":
            res = qg.get_graph_relationship_catalog()
            return _format_tool_payload(res, truncate=False)

        if name == "search_nodes":
            lim = int(tool_input.get("limit") or 40)
            nt = tool_input.get("node_type")
            if isinstance(nt, str) and not nt.strip():
                nt = None
            res = qg.search_nodes(
                str(tool_input.get("query", "")),
                node_type=nt,
                limit=min(max(lim, 1), 200),
            )
            return _format_tool_payload(res, truncate=False)

        if name == "get_neighbors":
            nid = str(tool_input["node_id"]).strip()
            if "|" not in nid and re.search(r"(?i)claim", nid):
                nid = normalize_claim_node_id(nid)
            res = qg.get_neighbors(nid)
            return json.dumps(res, indent=2)

        if name == "get_person_policies":
            pid = normalize_person_node_id(str(tool_input.get("person_node_id", "")))
            res = qg.get_person_policies(pid)
            return _format_tool_payload(res, truncate=False)

        if name == "policies_with_related_coparties":
            pid = normalize_person_node_id(str(tool_input.get("person_node_id", "")))
            res = qg.policies_with_related_coparties(pid)
            return _format_tool_payload(res, truncate=False)

        if name == "get_claim_network":
            cid = normalize_claim_node_id(str(tool_input.get("claim_node_id", "")))
            res = qg.get_claim_network(cid)
            return _format_tool_payload(res, truncate=False)

        if name == "get_claim_subgraph_summary":
            depth = int(tool_input.get("max_depth") or 3)
            depth = max(1, min(depth, 8))
            cid = normalize_claim_node_id(str(tool_input.get("claim_node_id", "")))
            res = qg.get_claim_subgraph_summary(cid, max_depth=depth)
            return _format_tool_payload(res, truncate=False)

        if name == "get_person_subgraph_summary":
            pid = normalize_person_node_id(str(tool_input.get("person_node_id", "")))
            depth = int(tool_input.get("max_depth") or 2)
            depth = max(1, min(depth, 8))
            res = qg.get_person_subgraph_summary(pid, max_depth=depth)
            return _format_tool_payload(res, truncate=False)

        if name == "get_policy_network":
            pid = normalize_policy_node_id(str(tool_input.get("policy_node_id", "")))
            res = qg.get_policy_network(pid)
            return _format_tool_payload(res, truncate=False)

        if name == "find_shared_bank_accounts":
            res = qg.find_shared_bank_accounts()
            return _format_tool_payload(res, truncate=False)

        if name == "find_related_people_clusters":
            res = qg.find_related_people_clusters()
            return _format_tool_payload(res, truncate=False)

        if name == "find_business_connection_patterns":
            res = qg.find_business_connection_patterns()
            return _format_tool_payload(res, truncate=False)

        return f"Unknown tool: {name}"
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"


def execute_graph_tool(name: str, tool_input: dict[str, Any], *, for_model: bool = True) -> str:
    """Run one tool. When ``for_model`` is True, truncate for the planner's context window."""
    raw = _execute_graph_tool_raw(name, tool_input)
    return _truncate(raw) if for_model else raw


@dataclass
class ToolAgentStep:
    tool: str
    input: dict[str, Any]
    result_preview: str
    planner_phase: int = 0


@dataclass
class JudgeRoundInfo:
    """One coverage-judge invocation after a planner phase (not user-facing prose)."""

    satisfied: bool
    rationale: str
    feedback_for_planner: str | None = None


@dataclass
class ToolAgentResult:
    question: str
    steps: list[ToolAgentStep] = field(default_factory=list)
    final_text: str = ""
    error: str | None = None
    raw_messages: int = 0
    graph_focus_node_id: str | None = None
    synthesis_rationale: str = ""
    judge_rounds: list[JudgeRoundInfo] = field(default_factory=list)


def run_planner_phase(
    client: Any,
    contents: Any,
    out_steps: list[ToolAgentStep],
    *,
    planner_phase: int,
    max_rounds: int = 14,
) -> tuple[Any, int]:
    """
    Run the tool-use loop until the model stops requesting tools or ``max_rounds`` is hit.

    * **Gemini:** ``client`` is ``google.genai.Client``; ``contents`` is ``list[types.Content]``.
    * **Anthropic:** ``client`` is ``anthropic.Anthropic``; ``contents`` is a ``list`` of Messages API turns.
    * **Ollama:** ``client`` is ``ollama.Client``; ``contents`` is a ``list`` of chat dicts / Messages
      starting with ``system`` + ``user``.

    Appends :class:`ToolAgentStep` rows with **full** tool output text in ``result_preview`` (the UI
    may truncate for display). Sends **truncated** tool results back to the model.

    Returns ``(contents, api_calls_made)``.
    """
    def _append_step(name: str, inp: dict[str, Any], body_full: str, phase: int) -> None:
        out_steps.append(
            ToolAgentStep(
                tool=name,
                input=dict(inp),
                result_preview=body_full,
                planner_phase=phase,
            )
        )

    if investigation_llm_backend() == "ollama":
        from src.llm.local_ollama import run_planner_phase_ollama

        return run_planner_phase_ollama(
            client,
            contents,
            out_steps,
            model=OLLAMA_MODEL,
            graph_tool_specs=GRAPH_TOOLS,
            execute_tool=execute_graph_tool,
            truncate_for_model=_truncate,
            append_tool_step=_append_step,
            planner_phase=planner_phase,
            max_rounds=max_rounds,
        )

    if investigation_llm_backend() == "anthropic":
        from src.llm.anthropic_llm import run_planner_phase_anthropic

        return run_planner_phase_anthropic(
            client,
            contents,
            out_steps,
            model=ANTHROPIC_MODEL,
            graph_tool_specs=GRAPH_TOOLS,
            system_instruction=SYSTEM_TOOL_AGENT,
            execute_tool=execute_graph_tool,
            truncate_for_model=_truncate,
            append_tool_step=_append_step,
            planner_phase=planner_phase,
            max_rounds=max_rounds,
        )

    from src.llm.gemini_llm import run_planner_phase_genai

    return run_planner_phase_genai(
        client,
        contents,
        out_steps,
        model=MODEL,
        graph_tool_specs=GRAPH_TOOLS,
        system_instruction=SYSTEM_TOOL_AGENT,
        execute_tool=execute_graph_tool,
        truncate_for_model=_truncate,
        append_tool_step=_append_step,
        planner_phase=planner_phase,
        max_rounds=max_rounds,
    )


def run_tool_planner_agent(
    question: str,
    *,
    max_rounds: int | None = None,
) -> ToolAgentResult:
    """
    Full investigation: planner ↔ coverage judge (uncapped outer loop), then synthesis
    for the user-visible answer and graph focus.

    ``max_rounds`` overrides ``INVESTIGATION_PLANNER_MAX_ROUNDS`` / backend defaults when set.
    """
    from src.llm.orchestration import run_investigation_orchestrator

    return run_investigation_orchestrator(question, planner_max_rounds_per_phase=max_rounds)
