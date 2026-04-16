"""
**Tool-planner agent:** Claude with native ``tool_use`` calls into ``query_graph``
functions. Plans multi-step retrieval (search → specialized query) instead of a
single intent label.
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

import anthropic
import pandas as pd

from src.graph_query import query_graph as qg
from src.llm.prompts import SYSTEM_TOOL_AGENT
from src.llm.result_serialize import investigation_payload_to_text

MAX_TOOL_CHARS = 14_000
MODEL = "claude-opus-4-6"


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


# Anthropic Messages API tool definitions (input_schema = JSON Schema subset)
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
                "claim_node_id": {"type": "string", "description": "Claim node id."},
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
                "claim_node_id": {"type": "string", "description": "Claim node id."},
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


def _format_tool_payload(payload: dict[str, Any]) -> str:
    """Turn a query_graph return dict into readable text for the model."""
    lines: list[str] = []
    if payload.get("summary"):
        lines.append(f"summary: {payload['summary']}")
    if payload.get("explanation_plain"):
        lines.append(f"explanation_plain:\n{payload['explanation_plain']}")
    if payload.get("evidence_bullets"):
        eb = payload["evidence_bullets"]
        if isinstance(eb, list):
            lines.append("evidence_bullets:\n" + "\n".join(f"- {b}" for b in eb[:60]))
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
    return _truncate("\n\n".join(lines))


def execute_graph_tool(name: str, tool_input: dict[str, Any]) -> str:
    """Run one tool; return text for tool_result content."""
    try:
        if name == "summarize_graph":
            out = qg.summarize_graph()
            return _truncate(json.dumps(out, indent=2, default=str))

        if name == "get_graph_relationship_catalog":
            res = qg.get_graph_relationship_catalog()
            return _format_tool_payload(res)

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
            return _format_tool_payload(res)

        if name == "get_neighbors":
            res = qg.get_neighbors(str(tool_input["node_id"]))
            return _truncate(json.dumps(res, indent=2))

        if name == "get_person_policies":
            pid = normalize_person_node_id(str(tool_input.get("person_node_id", "")))
            res = qg.get_person_policies(pid)
            return _format_tool_payload(res)

        if name == "policies_with_related_coparties":
            pid = normalize_person_node_id(str(tool_input.get("person_node_id", "")))
            res = qg.policies_with_related_coparties(pid)
            return _format_tool_payload(res)

        if name == "get_claim_network":
            res = qg.get_claim_network(str(tool_input["claim_node_id"]))
            return _format_tool_payload(res)

        if name == "get_claim_subgraph_summary":
            depth = int(tool_input.get("max_depth") or 3)
            depth = max(1, min(depth, 8))
            res = qg.get_claim_subgraph_summary(
                str(tool_input["claim_node_id"]),
                max_depth=depth,
            )
            return _format_tool_payload(res)

        if name == "get_person_subgraph_summary":
            pid = normalize_person_node_id(str(tool_input.get("person_node_id", "")))
            depth = int(tool_input.get("max_depth") or 2)
            depth = max(1, min(depth, 8))
            res = qg.get_person_subgraph_summary(pid, max_depth=depth)
            return _format_tool_payload(res)

        if name == "get_policy_network":
            pid = normalize_policy_node_id(str(tool_input.get("policy_node_id", "")))
            res = qg.get_policy_network(pid)
            return _format_tool_payload(res)

        if name == "find_shared_bank_accounts":
            res = qg.find_shared_bank_accounts()
            return _format_tool_payload(res)

        if name == "find_related_people_clusters":
            res = qg.find_related_people_clusters()
            return _format_tool_payload(res)

        if name == "find_business_connection_patterns":
            res = qg.find_business_connection_patterns()
            return _format_tool_payload(res)

        return f"Unknown tool: {name}"
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"


@dataclass
class ToolAgentStep:
    tool: str
    input: dict[str, Any]
    result_preview: str


@dataclass
class ToolAgentResult:
    question: str
    steps: list[ToolAgentStep] = field(default_factory=list)
    final_text: str = ""
    error: str | None = None
    raw_messages: int = 0


def run_tool_planner_agent(
    question: str,
    *,
    max_rounds: int = 24,
) -> ToolAgentResult:
    """
    ReAct-style loop: Claude may call graph tools until it produces a final text answer.
    """
    out = ToolAgentResult(question=question)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        out.error = "ANTHROPIC_API_KEY is not set."
        return out

    client = anthropic.Anthropic(api_key=api_key)
    system = [
        {
            "type": "text",
            "text": SYSTEM_TOOL_AGENT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

    final_text_parts: list[str] = []
    api_calls = 0

    while api_calls < max_rounds:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=system,
            tools=GRAPH_TOOLS,
            messages=messages,
        )
        api_calls += 1
        out.raw_messages += 1

        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]

        for tb in text_blocks:
            if hasattr(tb, "text"):
                final_text_parts.append(tb.text)

        if not tool_uses:
            break

        result_blocks: list[dict[str, Any]] = []
        for block in tool_uses:
            tname = block.name
            tinp = block.input if isinstance(block.input, dict) else {}
            body = execute_graph_tool(tname, tinp)
            out.steps.append(
                ToolAgentStep(tool=tname, input=dict(tinp), result_preview=body[:16000])
            )
            result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": body,
                }
            )
        messages.append({"role": "user", "content": result_blocks})

    out.final_text = "\n\n".join(final_text_parts).strip()
    if not out.final_text and out.steps:
        out.final_text = (
            "The model returned tool results but no final narrative. "
            "Inspect the tool trace above or re-run with a more specific question."
        )
    return out
