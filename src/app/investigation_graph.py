"""
Build a single **summary subgraph** for the main app after a tool-planner run.

Collects anchor node ids from tool inputs and from ``Type|id`` patterns in
previews and the answer, then builds a **query-tailored** view:

* **Person–person** — only people and personal-tie edges (when the question/tools
  indicate family/social/related-party focus).
* **Claims / policies** — people, claims, and policies only (drops addresses, banks, …).
* **Financial / business** — focused type sets for those tools.
* **Neighbourhood** — full hop expansion (exploratory; use Interactive Graph for the whole book).
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
MAX_ANCHORS = 25

# Short UI lines (keys match :func:`infer_summary_view_mode`).
SUMMARY_VIEW_CAPTIONS: dict[str, str] = {
    "p2p": (
        "**Person–person view** — only personal ties (spouse, related, POA/HIPAA/diagnosing, …). "
        "Open **Interactive Graph** to explore the full network."
    ),
    "claims_policies": (
        "**Claims / policies view** — when a **claim** or **policy** was in scope, the graph prefers the "
        "same entities the claim/policy tools surface (claim ↔ policy ↔ people), not a random hop through banks/addresses."
    ),
    "financial": (
        "**Financial view** — people, bank accounts, and addresses tied to this investigation."
    ),
    "business": (
        "**Business view** — people, businesses, and addresses tied to this investigation."
    ),
    "neighbourhood": (
        "**Neighbourhood view** — all entity types within the hop count around anchors. "
        "Use **Interactive Graph** for unconstrained exploration."
    ),
}


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
    from src.llm.tool_agent import normalize_person_node_id, normalize_policy_node_id

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
        v = str(inp.get("claim_node_id", "")).strip()
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
    return {a for a in anchors if a and "|" in a}


def gather_priority_anchor_order(tr: "ToolAgentResult") -> list[str]:
    """
    **Most important first:** explicit tool inputs (what the planner targeted), then ids parsed
    from tool result text, then ids only appearing in the final narrative (often noisier).
    """
    ordered: list[str] = []
    seen: set[str] = set()

    for step in tr.steps:
        for aid in _anchors_from_tool_input(step.tool, step.input):
            if aid and "|" in aid and aid not in seen:
                seen.add(aid)
                ordered.append(aid)

    for step in tr.steps:
        for x in extract_node_ids_from_text(step.result_preview):
            if x not in seen and "|" in x:
                seen.add(x)
                ordered.append(x)

    for x in extract_node_ids_from_text(tr.final_text):
        if x not in seen and "|" in x:
            seen.add(x)
            ordered.append(x)

    return ordered


def pick_focus_node(tr: "ToolAgentResult", anchors: set[str], G) -> str | None:
    """Prefer the entity type the tools were aimed at (claim, policy, person)."""
    if not anchors:
        return None
    in_g = {a for a in anchors if a in G}
    if not in_g:
        return None
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


def _p2p_question_hints(q: str) -> bool:
    ql = (q or "").lower()
    phrases = (
        "person-to-person",
        "person to person",
        "between people",
        "relationship between",
        "family",
        "spouse",
        "relative",
        "related people",
        "social cluster",
        "who knows",
        "related to each other",
        "connected people",
        "people clusters",
        "related party",
        "related parties",
        "same policy as someone they know",
        "coparty",
        "co-party",
    )
    return any(p in ql for p in phrases)


def infer_summary_view_mode(tr: "ToolAgentResult") -> str:
    """
    Infer how to tailor the summary graph from the **question** and **tools used**.

    Returns one of: ``p2p``, ``claims_policies``, ``financial``, ``business``, ``neighbourhood``.
    """
    tools = [s.tool for s in tr.steps]
    q = tr.question or ""

    if "find_related_people_clusters" in tools or "policies_with_related_coparties" in tools:
        return "p2p"
    if _p2p_question_hints(q):
        return "p2p"
    if "find_shared_bank_accounts" in tools:
        return "financial"
    if "find_business_connection_patterns" in tools:
        return "business"
    if any(
        t in tools
        for t in (
            "get_claim_network",
            "get_claim_subgraph_summary",
            "get_policy_network",
            "get_person_policies",
            "get_person_subgraph_summary",
        )
    ):
        return "claims_policies"
    if any("claim" in t or "policy" in t for t in tools):
        return "claims_policies"
    return "neighbourhood"


def _filter_node_types(G, visible: set[str], allowed: set[str]) -> set[str]:
    return {n for n in visible if n in G and G.nodes[n].get("node_type", "Unknown") in allowed}


def _limited_anchors(in_graph: set[str], anchor_order: list[str]) -> list[str]:
    """Cap anchors but keep tool-targeted ids first."""
    ordered = [a for a in anchor_order if a in in_graph]
    if len(ordered) >= MAX_ANCHORS:
        return ordered[:MAX_ANCHORS]
    rest = sorted(in_graph - set(ordered))
    return ordered + rest[: max(0, MAX_ANCHORS - len(ordered))]


def compute_claim_core_visible(
    G,
    claim_ids: set[str],
    *,
    max_nodes: int,
) -> tuple[set[str], str | None]:
    """
    Dense slice aligned with ``get_claim_network``: claim, policies, insureds/agents,
    and people tied to the claim—without unrelated N-hop noise.
    """
    from src.graph_query.query_graph import _collect_people_linked_to_claim

    visible: set[str] = set()
    policy_ids: set[str] = set()
    for cid in sorted(claim_ids):
        if cid not in G or G.nodes[cid].get("node_type") != "Claim":
            continue
        visible.add(cid)
        for row in _collect_people_linked_to_claim(G, cid):
            visible.add(row["person_node_id"])
        for succ in G.successors(cid):
            if G.nodes[succ].get("node_type") != "Policy":
                continue
            if G.edges[cid, succ].get("edge_type") != "IS_CLAIM_AGAINST_POLICY":
                continue
            visible.add(succ)
            policy_ids.add(succ)
    for pid in policy_ids:
        for pred in G.predecessors(pid):
            if G.nodes[pred].get("node_type") != "Person":
                continue
            et = G.edges[pred, pid].get("edge_type")
            if et in ("IS_COVERED_BY", "SOLD_POLICY"):
                visible.add(pred)

    visible = {n for n in visible if n in G}
    claims_in = [c for c in claim_ids if c in visible]
    focus = sorted(claims_in)[0] if claims_in else None

    if len(visible) > max_nodes:
        cl = {n for n in visible if G.nodes[n].get("node_type") == "Claim"}
        pol = {n for n in visible if G.nodes[n].get("node_type") == "Policy"}
        pers = {n for n in visible if G.nodes[n].get("node_type") == "Person"}
        out = set(cl) | set(pol)
        for p in sorted(pers):
            if len(out) >= max_nodes:
                break
            out.add(p)
        visible = out
        if focus and focus not in visible:
            focus = sorted([c for c in cl & visible])[0] if cl & visible else None
    return visible, focus


def compute_policy_core_visible(
    G,
    policy_ids: set[str],
    *,
    max_nodes: int,
) -> tuple[set[str], str | None]:
    """Aligned with ``get_policy_network``: policy, people on it, claims against it."""
    visible: set[str] = set()
    for pid in sorted(policy_ids):
        if pid not in G or G.nodes[pid].get("node_type") != "Policy":
            continue
        visible.add(pid)
        for pred in G.predecessors(pid):
            nt = G.nodes[pred].get("node_type")
            et = G.edges[pred, pid].get("edge_type")
            if nt == "Person" and et in ("IS_COVERED_BY", "SOLD_POLICY"):
                visible.add(pred)
            if nt == "Claim" and et == "IS_CLAIM_AGAINST_POLICY":
                visible.add(pred)
    visible = {n for n in visible if n in G}
    pol_in = [p for p in policy_ids if p in visible]
    focus = sorted(pol_in)[0] if pol_in else None
    if len(visible) > max_nodes:
        pol = {n for n in visible if G.nodes[n].get("node_type") == "Policy"}
        clm = {n for n in visible if G.nodes[n].get("node_type") == "Claim"}
        pers = {n for n in visible if G.nodes[n].get("node_type") == "Person"}
        out = set(pol) | set(clm)
        for p in sorted(pers):
            if len(out) >= max_nodes:
                break
            out.add(p)
        visible = out
    return visible, focus


def compute_investigation_visible_nodes(
    G,
    anchors: set[str],
    *,
    hop_depth: int,
    max_nodes: int = MAX_EXPAND_NODES,
    anchor_order: list[str] | None = None,
    focus_hint: str | None = None,
) -> tuple[set[str], str | None]:
    """
    Expand anchors with undirected neighborhoods; shrink hop or trim if too large.

    Returns ``(visible_node_ids, focus_node_id)`` for pyvis; empty set if nothing in-graph.
    """
    import networkx as nx

    if not isinstance(G, nx.DiGraph):
        raise TypeError("G must be a networkx.DiGraph")

    from src.app.graph_viz import nodes_within_depth

    in_graph = {a for a in anchors if a in G}
    if not in_graph:
        return set(), None

    order = anchor_order if anchor_order is not None else sorted(in_graph)
    limited = _limited_anchors(in_graph, order)
    focus = focus_hint if (focus_hint and focus_hint in limited) else _pick_focus_node(set(limited))

    h = max(1, min(int(hop_depth), 8))
    for trial_h in range(h, 0, -1):
        union: set[str] = set()
        for a in limited:
            union |= nodes_within_depth(G, a, trial_h)
        if len(union) <= max_nodes:
            fg = focus if (focus and focus in union) else _pick_focus_node(set(limited) & union)
            return union, fg

    union = set()
    for a in limited:
        union |= nodes_within_depth(G, a, 1)
    trimmed = _trim_to_max_nodes(union, set(limited), max_nodes)
    fg = focus if (focus and focus in trimmed) else _pick_focus_node(set(limited) & trimmed)
    return trimmed, fg


def compute_p2p_visible_nodes(
    G,
    anchors: set[str],
    *,
    hop_depth: int,
    max_nodes: int = MAX_EXPAND_NODES,
) -> tuple[set[str], str | None]:
    """
    Only **Person** nodes, connected via **P**erson–**P**erson relationship edges
    (see ``PERSON_TO_PERSON_RELATIONSHIP_TYPES`` in ``query_graph``).
    """
    import networkx as nx

    from src.graph_query.query_graph import PERSON_TO_PERSON_RELATIONSHIP_TYPES

    if not isinstance(G, nx.DiGraph):
        raise TypeError("G must be a networkx.DiGraph")

    person_seeds = {a for a in anchors if a in G and G.nodes[a].get("node_type") == "Person"}
    if not person_seeds:
        return set(), None

    U = nx.Graph()
    for u, v, d in G.edges(data=True):
        et = d.get("edge_type", "")
        if et not in PERSON_TO_PERSON_RELATIONSHIP_TYPES:
            continue
        if G.nodes[u].get("node_type") == "Person" and G.nodes[v].get("node_type") == "Person":
            U.add_edge(u, v)

    h = max(1, min(int(hop_depth), 8))
    union: set[str] = set()
    for seed in sorted(person_seeds)[:MAX_ANCHORS]:
        if seed not in U:
            union.add(seed)
            continue
        lengths = nx.single_source_shortest_path_length(U, seed, cutoff=h)
        union |= set(lengths.keys())

    if len(union) > max_nodes:
        union = _trim_to_max_nodes(union, person_seeds, max_nodes)

    focus = next((a for a in sorted(person_seeds) if a in union), None)
    if focus is None and union:
        focus = sorted(union)[0]
    return union, focus


def compute_summary_visible_nodes(
    G,
    tr: "ToolAgentResult",
    anchors: set[str],
    *,
    hop_depth: int,
    max_nodes: int = MAX_EXPAND_NODES,
) -> tuple[set[str], str | None, str, frozenset[str] | None, str | None]:
    """
    Tailored summary: prefer **tool-aligned** claim/policy cores, then neighbourhoods.

    Returns ``(visible_nodes, focus_node, view_mode, edge_type_filter, focus_hint_caption)``.
    The last element is an optional short line for the UI (e.g. claim-aligned slice).
    ``edge_type_filter`` is set only for the person–person view.
    """
    from src.graph_query.query_graph import PERSON_TO_PERSON_RELATIONSHIP_TYPES

    anchor_order = gather_priority_anchor_order(tr)
    focus_hint = pick_focus_node(tr, anchors, G)

    mode = infer_summary_view_mode(tr)
    person_seeds = {a for a in anchors if a in G and G.nodes[a].get("node_type") == "Person"}

    if mode == "p2p" and not person_seeds:
        mode = "neighbourhood"

    if mode == "p2p":
        vis, foc = compute_p2p_visible_nodes(G, anchors, hop_depth=hop_depth, max_nodes=max_nodes)
        if vis:
            fg = pick_focus_node(tr, set(vis) & anchors, G) or foc
            if fg and fg not in vis:
                fg = foc
            return vis, fg or foc, mode, PERSON_TO_PERSON_RELATIONSHIP_TYPES, None
        mode = "neighbourhood"

    claim_ids = {a for a in anchors if a in G and G.nodes[a].get("node_type") == "Claim"}
    policy_ids = {a for a in anchors if a in G and G.nodes[a].get("node_type") == "Policy"}

    if mode == "claims_policies":
        if claim_ids:
            vis, foc = compute_claim_core_visible(G, claim_ids, max_nodes=max_nodes)
            if vis:
                fg = foc if (foc and foc in vis) else focus_hint if (focus_hint and focus_hint in vis) else _pick_focus_node(vis)
                cap = (
                    "**Claim-focused graph** — claim, linked policies, insureds/agents, and people tied to the "
                    "claim (same structure as the claim network tool)."
                )
                return vis, fg, mode, None, cap
        if policy_ids and not claim_ids:
            vis, foc = compute_policy_core_visible(G, policy_ids, max_nodes=max_nodes)
            if vis:
                fg = foc if (foc and foc in vis) else focus_hint if (focus_hint and focus_hint in vis) else _pick_focus_node(vis)
                cap = (
                    "**Policy-focused graph** — policy, people on it, and claims filed against it "
                    "(aligned with the policy network tool)."
                )
                return vis, fg, mode, None, cap

    vis, foc = compute_investigation_visible_nodes(
        G,
        anchors,
        hop_depth=hop_depth,
        max_nodes=max_nodes,
        anchor_order=anchor_order,
        focus_hint=focus_hint,
    )
    if not vis:
        return set(), None, mode, None, None

    if mode == "claims_policies":
        filtered = _filter_node_types(G, vis, {"Person", "Claim", "Policy"})
        if filtered:
            fg = (
                foc
                if (foc and foc in filtered)
                else focus_hint
                if (focus_hint and focus_hint in filtered)
                else _pick_focus_node(anchors & filtered)
            )
            return filtered, fg, mode, None, None
        return vis, foc, "neighbourhood", None, None

    if mode == "financial":
        filtered = _filter_node_types(G, vis, {"Person", "BankAccount", "Address"})
        if filtered:
            fg = (
                foc
                if (foc and foc in filtered)
                else focus_hint
                if (focus_hint and focus_hint in filtered)
                else _pick_focus_node(anchors & filtered)
            )
            return filtered, fg, mode, None, None
        return vis, foc, "neighbourhood", None, None

    if mode == "business":
        filtered = _filter_node_types(G, vis, {"Person", "Business", "Address"})
        if filtered:
            fg = (
                foc
                if (foc and foc in filtered)
                else focus_hint
                if (focus_hint and focus_hint in filtered)
                else _pick_focus_node(anchors & filtered)
            )
            return filtered, fg, mode, None, None
        return vis, foc, "neighbourhood", None, None

    return vis, foc, "neighbourhood", None, None
