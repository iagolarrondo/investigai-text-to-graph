"""
Build a single **summary subgraph** for the main app after a tool-planner run.

Collects anchor node ids from tool inputs, from ``Type|id`` patterns in
previews and the answer, from synthesis ``graph_focus_node_id`` (typed or raw
``node_id`` as in ``nodes.csv``), then builds a **single focus node** plus an **undirected
N-hop ego network** (all node and edge types in that ball). Hop count comes from the UI.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.tool_agent import ToolAgentResult

# Matches demo-style ids: Person|1001, Claim|C001, Policy|POL001, etc.
_NODE_ID_RE = re.compile(
    r"\b(Person|Claim|Policy|Address|BankAccount|Business)\|[^\s\]\)\"',]+"
)

MAX_EXPAND_NODES = 120


def extract_node_ids_from_text(text: str) -> set[str]:
    """Parse ``node_type|…`` tokens from arbitrary text (tables, prose)."""
    if not text:
        return set()
    out: set[str] = set()
    for m in _NODE_ID_RE.finditer(text):
        raw = m.group(0)
        out.add(raw.rstrip(".,;:!?)"))
    return out


def _anchors_from_tool_input(tool: str, inp: object) -> set[str]:
    """Deterministic anchors from a single tool call (mirrors ``execute_graph_tool``)."""
    from src.llm.tool_agent import (
        normalize_claim_node_id,
        normalize_person_node_id,
        normalize_policy_node_id,
    )

    out: set[str] = set()
    if not isinstance(inp, dict):
        return out

    if tool == "get_neighbors":
        v = str(inp.get("node_id", "")).strip()
        if v:
            out.add(v)
    elif tool in ("get_person_policies", "policies_with_related_coparties", "get_person_subgraph_summary"):
        v = normalize_person_node_id(str(inp.get("person_node_id", "")))
        if v:
            out.add(v)
    elif tool in ("get_claim_network", "get_claim_subgraph_summary"):
        v = normalize_claim_node_id(str(inp.get("claim_node_id", "")))
        if v:
            out.add(v)
    elif tool == "get_policy_network":
        v = normalize_policy_node_id(str(inp.get("policy_node_id", "")))
        if v:
            out.add(v)
    return out


def gather_investigation_anchors(tr: "ToolAgentResult") -> set[str]:
    """Union of structured tool inputs and id-like strings in previews + answer."""
    anchors: set[str] = set()
    for step in tr.steps:
        anchors |= _anchors_from_tool_input(step.tool, step.input)
        anchors |= extract_node_ids_from_text(step.result_preview)
    anchors |= extract_node_ids_from_text(tr.final_text)
    gf = getattr(tr, "graph_focus_node_id", None)
    if isinstance(gf, str) and (sid := gf.strip()):
        anchors.add(sid)
    # Do not require ``Type|…`` — graph exports use raw ids (e.g. ``person_5001``, ``address_9001``).
    return {a for a in anchors if a}


def gather_priority_anchor_order(tr: "ToolAgentResult") -> list[str]:
    """
    **Most important first:** explicit tool inputs (what the planner targeted), then ids parsed
    from tool result text, then ids only appearing in the final narrative (often noisier).
    """
    ordered: list[str] = []
    seen: set[str] = set()

    focus = getattr(tr, "graph_focus_node_id", None)
    if isinstance(focus, str) and (fid := focus.strip()):
        ordered.append(fid)
        seen.add(fid)

    for step in tr.steps:
        for aid in _anchors_from_tool_input(step.tool, step.input):
            if aid and aid not in seen:
                seen.add(aid)
                ordered.append(aid)

    for step in tr.steps:
        for x in extract_node_ids_from_text(step.result_preview):
            if x not in seen:
                seen.add(x)
                ordered.append(x)

    for x in extract_node_ids_from_text(tr.final_text):
        if x not in seen:
            seen.add(x)
            ordered.append(x)

    return ordered


def pick_focus_node(tr: "ToolAgentResult", anchors: set[str], G) -> str | None:
    """Prefer synthesis graph focus, then the entity type the tools were aimed at (claim, policy, person)."""
    if not anchors:
        return None
    in_g = {a for a in anchors if a in G}
    if not in_g:
        return None
    synth = getattr(tr, "graph_focus_node_id", None)
    if isinstance(synth, str) and synth.strip():
        sid = synth.strip()
        if sid in G.nodes:
            return sid
    tools = [s.tool for s in tr.steps]

    if any(t in tools for t in ("get_claim_network", "get_claim_subgraph_summary")):
        claims = [a for a in in_g if G.nodes[a].get("node_type") == "Claim"]
        if claims:
            return sorted(claims)[0]
    if "get_policy_network" in tools:
        pols = [a for a in in_g if G.nodes[a].get("node_type") == "Policy"]
        if pols:
            return sorted(pols)[0]
    if any(
        t in tools
        for t in (
            "get_person_policies",
            "get_person_subgraph_summary",
            "policies_with_related_coparties",
        )
    ):
        pers = [a for a in in_g if G.nodes[a].get("node_type") == "Person"]
        if pers:
            return sorted(pers)[0]

    return _pick_focus_node(anchors)


def _pick_focus_node(anchors: set[str]) -> str | None:
    if not anchors:
        return None
    for prefix in ("Claim|", "Person|", "Policy|"):
        for a in sorted(anchors):
            if a.startswith(prefix):
                return a
    return sorted(anchors)[0]


def _trim_to_max_nodes(union: set[str], priority: set[str], max_nodes: int) -> set[str]:
    if len(union) <= max_nodes:
        return union
    pri_sorted = [x for x in sorted(priority) if x in union]
    rest = sorted(union - set(pri_sorted))
    out: list[str] = []
    for x in pri_sorted + rest:
        if len(out) >= max_nodes:
            break
        out.append(x)
    return set(out)


def compute_hop_ego_visible(
    G,
    focus: str,
    *,
    hop_depth: int,
    max_nodes: int,
) -> set[str]:
    """Undirected hop ball around ``focus``; shrink hop then trim if still above ``max_nodes``."""
    import networkx as nx

    from src.app.graph_viz import nodes_within_depth

    if not isinstance(G, nx.DiGraph):
        raise TypeError("G must be a networkx.DiGraph")
    if focus not in G:
        return set()

    h = max(1, min(int(hop_depth), 8))
    for trial_h in range(h, 0, -1):
        vis = nodes_within_depth(G, focus, trial_h)
        if len(vis) <= max_nodes:
            return vis
    vis = nodes_within_depth(G, focus, 1)
    return _trim_to_max_nodes(vis, {focus}, max_nodes)


def compute_summary_visible_nodes(
    G,
    tr: "ToolAgentResult",
    anchors: set[str],
    *,
    hop_depth: int,
    max_nodes: int = MAX_EXPAND_NODES,
) -> tuple[set[str], str | None, str, frozenset[str] | None, str | None]:
    """
    Pick one **focus** node (synthesis ``graph_focus_node_id``, then tool/anchor heuristics),
    then show the **undirected hop ball** around it — every node type and edge type in range.

    Returns ``(visible_nodes, focus_node, "hop_ego", None, caption)``.
    """
    in_graph = {a for a in anchors if a in G}
    if not in_graph:
        return set(), None, "hop_ego", None, None

    focus = pick_focus_node(tr, in_graph, G)
    if not focus or focus not in G:
        focus = _pick_focus_node(in_graph)
    if not focus or focus not in G:
        return set(), None, "hop_ego", None, None

    visible = compute_hop_ego_visible(G, focus, hop_depth=hop_depth, max_nodes=max_nodes)
    if not visible:
        return set(), None, "hop_ego", None, None

    cap = (
        f"**Center:** `{focus}` — undirected neighbourhood up to **{hop_depth}** hop(s); "
        f"all entity types in range (**{len(visible)}** nodes; trimmed if above the cap)."
    )
    return visible, focus, "hop_ego", None, cap
