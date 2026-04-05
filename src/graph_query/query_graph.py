"""
Load the prototype graph from CSV and run small queries in memory with NetworkX.

Reads ``data/processed/nodes.csv`` and ``data/processed/edges.csv`` (from
``build_graph_files.py``), builds a directed graph, and exposes helpers for
exploration and **PoC v1 investigation-style** summaries (often as pandas
DataFrames).

Run from the project root::

    python src/graph_query/query_graph.py

Call ``load_graph()`` before using the query functions (``main()`` does this).
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from pprint import pprint

import networkx as nx
import pandas as pd

# Project root: src/graph_query -> src -> repo root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
NODES_CSV = PROJECT_ROOT / "data" / "processed" / "nodes.csv"
EDGES_CSV = PROJECT_ROOT / "data" / "processed" / "edges.csv"

# In-memory graph, filled by load_graph(). Query helpers read from here.
_graph: nx.DiGraph | None = None


def _require_graph() -> nx.DiGraph:
    if _graph is None:
        raise RuntimeError("Graph not loaded yet. Call load_graph() first.")
    return _graph


def get_graph() -> nx.DiGraph:
    """Return the loaded directed graph (call ``load_graph()`` first)."""
    return _require_graph()


def _parse_properties_json(raw) -> dict:
    """Parse node/edge ``properties_json`` string to a dict; empty dict on failure."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}


def _node_row(G: nx.DiGraph, node_id: str) -> dict:
    data = dict(G.nodes[node_id])
    data["node_id"] = node_id
    data["parsed_props"] = _parse_properties_json(data.get("properties_json"))
    return data


def _person_address_node(G: nx.DiGraph, person_id: str) -> str | None:
    """Return the Address node_id linked by person -> LOCATED_IN -> address, if any."""
    for succ in G.successors(person_id):
        ed = G.edges[person_id, succ].get("edge_type")
        if ed == "LOCATED_IN" and G.nodes[succ].get("node_type") == "Address":
            return succ
    return None


def load_graph() -> nx.DiGraph:
    """
    Read the two CSV files and build a directed NetworkX graph.

    Each node carries ``node_type``, ``label``, ``source_table``, ``properties_json``.
    Each edge carries ``edge_id``, ``edge_type``, ``source_table``, ``properties_json``.
    """
    global _graph

    if not NODES_CSV.is_file() or not EDGES_CSV.is_file():
        raise FileNotFoundError(
            f"Missing {NODES_CSV} or {EDGES_CSV}. "
            "Run: python src/graph_build/build_graph_files.py"
        )

    nodes_df = pd.read_csv(NODES_CSV)
    edges_df = pd.read_csv(EDGES_CSV)

    G = nx.DiGraph()

    for _, row in nodes_df.iterrows():
        G.add_node(
            row["node_id"],
            node_type=row["node_type"],
            label=row["label"],
            source_table=row["source_table"],
            properties_json=row["properties_json"],
        )

    for _, row in edges_df.iterrows():
        G.add_edge(
            row["source_node_id"],
            row["target_node_id"],
            edge_id=row["edge_id"],
            edge_type=row["edge_type"],
            source_table=row["source_table"],
            properties_json=row["properties_json"],
        )

    _graph = G
    return G


def get_nodes_by_type(node_type: str) -> list[str]:
    """Return every ``node_id`` whose ``node_type`` matches (exact string)."""
    G = _require_graph()
    out: list[str] = []
    for nid, data in G.nodes(data=True):
        if data.get("node_type") == node_type:
            out.append(nid)
    return sorted(out)


def get_neighbors(node_id: str) -> dict[str, list[str]]:
    """
    Directed neighbors: ``outgoing`` (successors) and ``incoming`` (predecessors).
    """
    G = _require_graph()
    if node_id not in G:
        raise KeyError(f"Unknown node_id: {node_id!r}")
    return {
        "outgoing": sorted(G.successors(node_id)),
        "incoming": sorted(G.predecessors(node_id)),
    }


def get_edges_by_type(edge_type: str) -> list[dict]:
    """All edges with the given ``edge_type``, as dicts including source/target."""
    G = _require_graph()
    matches: list[dict] = []
    for u, v, data in G.edges(data=True):
        if data.get("edge_type") == edge_type:
            row = {"source": u, "target": v, **data}
            matches.append(row)
    matches.sort(key=lambda r: (r["source"], r["target"], r.get("edge_id", "")))
    return matches


def summarize_graph() -> dict:
    """
    Compact summary: node/edge counts and frequency by ``node_type`` / ``edge_type``.
    """
    G = _require_graph()

    node_type_counts: dict[str, int] = {}
    for _, data in G.nodes(data=True):
        nt = data.get("node_type", "(missing)")
        node_type_counts[nt] = node_type_counts.get(nt, 0) + 1

    edge_type_counts: dict[str, int] = {}
    for _, _, data in G.edges(data=True):
        et = data.get("edge_type", "(missing)")
        edge_type_counts[et] = edge_type_counts.get(et, 0) + 1

    return {
        "num_nodes": G.number_of_nodes(),
        "num_edges": G.number_of_edges(),
        "node_types": dict(sorted(node_type_counts.items())),
        "edge_types": dict(sorted(edge_type_counts.items())),
        "is_directed": G.is_directed(),
    }


def _narrate_claim_network(
    *,
    claim_node_id: str,
    policy_ids: list[str],
    claim_number: str,
    num_other_claims: int,
    other_claim_rows: list[dict],
    party_rows: list[dict],
    match_rows: list[dict],
) -> tuple[str, list[str]]:
    """
    Plain-English summary + bullet list of graph ids/relationships for investigators.
    """
    evidence: list[str] = []
    for pid in policy_ids:
        evidence.append(f"{claim_node_id} —[IS_CLAIM_AGAINST_POLICY]→ {pid}")
    for r in other_claim_rows:
        evidence.append(
            f"{r['claim_node_id']} —[IS_CLAIM_AGAINST_POLICY]→ {r['shared_policy_node_id']}"
        )

    agent_ids = {
        r["person_node_id"]
        for r in party_rows
        if r.get("relationship_to_policy") == "SOLD_POLICY"
    }
    claimant_person_ids = {r["person_node_id"] for r in match_rows}

    for r in party_rows:
        evidence.append(
            f"{r['person_node_id']} —[{r['relationship_to_policy']}]→ {r['policy_node_id']}"
        )

    for r in match_rows:
        evidence.append(
            f"Claimant on record matches resolved person {r['person_node_id']} "
            f"({r.get('person_label', '')}) via name + birth date on the graph."
        )

    parts = [
        f"We started from claim **{claim_number}** (`{claim_node_id}`) and followed "
        "the graph link that says this claim is filed against a policy."
    ]
    if policy_ids:
        pol = policy_ids[0]
        parts.append(f"It ties to policy **`{pol}`**.")
    else:
        parts.append("No policy node was linked from this claim in the graph.")

    if num_other_claims:
        parts.append(
            f"There are **{num_other_claims}** other claim(s) in the graph pointing at "
            "the same policy—useful for spotting concentrated activity or coordination."
        )
    else:
        parts.append("No other claims share that policy in this extract.")

    if party_rows:
        parts.append(
            "The tables list every person tied to that policy as insured or agent "
            "(edges `IS_COVERED_BY` and `SOLD_POLICY`)."
        )

    if agent_ids & claimant_person_ids:
        parts.append(
            "**Flag:** at least one person both **sold** the policy and **matches the "
            "claimant** on a linked claim—SIU often reviews that overlap for conflicts "
            "of interest."
        )
    elif match_rows:
        parts.append(
            "The claimant name on the claim record matches a **resolved person** node "
            "in the graph (see claimant match table)."
        )

    return " ".join(parts), evidence


def get_claim_network(claim_node_id: str) -> dict:
    """
    Build an **ego-centric “claim story”** slice: policy, peer claims, policy parties,
    and (if possible) the **Person** node that matches the claimant on the claim record.

    **How it works:** Starting at the Claim node, follow ``IS_CLAIM_AGAINST_POLICY`` to
    the Policy. From that policy, collect other Claim nodes (same edge type, reversed
    direction). Collect every Person with an edge **to** the policy (``IS_COVERED_BY``,
    ``SOLD_POLICY``). Finally, match ``FIRST_NAME`` / ``LAST_NAME`` / ``BIRTH_DATE``
    on the claim’s ``properties_json`` to Person node properties.

    **Returns:** a dict including DataFrames (``claim``, ``linked_policies``, …),
    machine ``summary``, plus **``explanation_plain``** (short prose for investigators)
    and **``evidence_bullets``** (key node ids and relationship types used).
    """
    G = _require_graph()
    if claim_node_id not in G:
        raise KeyError(f"Unknown node_id: {claim_node_id!r}")
    if G.nodes[claim_node_id].get("node_type") != "Claim":
        raise ValueError(f"Node {claim_node_id!r} is not a Claim node")

    cdata = _node_row(G, claim_node_id)
    cprops = cdata["parsed_props"]

    claim_df = pd.DataFrame(
        [
            {
                "node_id": claim_node_id,
                "label": cdata.get("label"),
                "CLAIM_NUMBER": cprops.get("CLAIM_NUMBER"),
                "POLICY_NUMBER": cprops.get("POLICY_NUMBER"),
                "CLAIM_STATUS_CODE": cprops.get("CLAIM_STATUS_CODE"),
                "claimant_FIRST_NAME": cprops.get("FIRST_NAME"),
                "claimant_LAST_NAME": cprops.get("LAST_NAME"),
                "claimant_BIRTH_DATE": cprops.get("BIRTH_DATE"),
            }
        ]
    )

    policy_ids: list[str] = []
    for succ in G.successors(claim_node_id):
        if G.edges[claim_node_id, succ].get("edge_type") == "IS_CLAIM_AGAINST_POLICY":
            if G.nodes[succ].get("node_type") == "Policy":
                policy_ids.append(succ)

    pol_rows = []
    for pid in policy_ids:
        d = _node_row(G, pid)
        p = d["parsed_props"]
        pol_rows.append(
            {
                "policy_node_id": pid,
                "label": d.get("label"),
                "POLICY_NUMBER": p.get("POLICY_NUMBER"),
                "POLICY_STATUS": p.get("POLICY_STATUS"),
            }
        )
    linked_policies = pd.DataFrame(pol_rows)

    other_claim_rows: list[dict] = []
    for pid in policy_ids:
        for pred in G.predecessors(pid):
            if pred == claim_node_id:
                continue
            if G.nodes[pred].get("node_type") != "Claim":
                continue
            if G.edges[pred, pid].get("edge_type") != "IS_CLAIM_AGAINST_POLICY":
                continue
            d = _node_row(G, pred)
            p = d["parsed_props"]
            other_claim_rows.append(
                {
                    "claim_node_id": pred,
                    "label": d.get("label"),
                    "CLAIM_NUMBER": p.get("CLAIM_NUMBER"),
                    "CLAIM_STATUS_CODE": p.get("CLAIM_STATUS_CODE"),
                    "claimant_FIRST_NAME": p.get("FIRST_NAME"),
                    "claimant_LAST_NAME": p.get("LAST_NAME"),
                    "shared_policy_node_id": pid,
                }
            )
    other_claims = pd.DataFrame(other_claim_rows)

    party_rows: list[dict] = []
    for pid in policy_ids:
        for pred in G.predecessors(pid):
            if G.nodes[pred].get("node_type") != "Person":
                continue
            et = G.edges[pred, pid].get("edge_type")
            if et not in ("IS_COVERED_BY", "SOLD_POLICY"):
                continue
            d = _node_row(G, pred)
            party_rows.append(
                {
                    "person_node_id": pred,
                    "person_label": d.get("label"),
                    "relationship_to_policy": et,
                    "policy_node_id": pid,
                    "EDGE_DETAIL": _parse_properties_json(
                        G.edges[pred, pid].get("properties_json")
                    ).get("EDGE_DETAIL"),
                }
            )
    people_on_policy = pd.DataFrame(party_rows)

    fn = (cprops.get("FIRST_NAME") or "").strip().upper()
    ln = (cprops.get("LAST_NAME") or "").strip().upper()
    bd = str(cprops.get("BIRTH_DATE") or "").strip()

    match_rows: list[dict] = []
    for pid in get_nodes_by_type("Person"):
        d = _node_row(G, pid)
        p = d["parsed_props"]
        pfn = (str(p.get("FIRST_NAME") or "")).strip().upper()
        pln = (str(p.get("LAST_NAME") or "")).strip().upper()
        pbd = str(p.get("BIRTH_DATE") or "").strip()
        if fn and ln and pfn == fn and pln == ln and (not bd or not pbd or bd[:10] == pbd[:10]):
            match_rows.append(
                {
                    "person_node_id": pid,
                    "person_label": d.get("label"),
                    "FIRST_NAME": p.get("FIRST_NAME"),
                    "LAST_NAME": p.get("LAST_NAME"),
                    "BIRTH_DATE": p.get("BIRTH_DATE"),
                }
            )
    claimant_match = pd.DataFrame(match_rows)

    summary = (
        f"Claim {claim_node_id}: {len(policy_ids)} linked polic(y/ies), "
        f"{len(other_claim_rows)} other claim(s) on same policy, "
        f"{len(party_rows)} person–policy link(s), "
        f"{len(match_rows)} claimant→person match(es)."
    )

    explanation_plain, evidence_bullets = _narrate_claim_network(
        claim_node_id=claim_node_id,
        policy_ids=policy_ids,
        claim_number=str(cprops.get("CLAIM_NUMBER") or claim_node_id),
        num_other_claims=len(other_claim_rows),
        other_claim_rows=other_claim_rows,
        party_rows=party_rows,
        match_rows=match_rows,
    )

    return {
        "summary": summary,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence_bullets,
        "claim": claim_df,
        "linked_policies": linked_policies,
        "other_claims_on_policy": other_claims,
        "people_linked_to_policy": people_on_policy,
        "claimant_person_match": claimant_match,
    }


def _nodes_within_undirected_depth(G: nx.DiGraph, start: str, max_depth: int) -> dict[str, int]:
    """
    Shortest-path distance from ``start`` when the graph is treated as **undirected**
    (relationships work both ways for “how many steps away” in a link chart).
    """
    if max_depth < 0:
        return {}
    U = G.to_undirected()
    dist: dict[str, int] = {start: 0}
    q: deque[str] = deque([start])
    while q:
        u = q.popleft()
        if dist[u] >= max_depth:
            continue
        for v in U.neighbors(u):
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def get_claim_subgraph_summary(claim_node_id: str, max_depth: int = 2) -> dict:
    """
    **Investigator-friendly neighborhood view:** every entity within ``max_depth``
    **undirected steps** of the claim (link-chart distance, not arrow semantics).

    Unlike ``get_claim_network``, this does **not** follow a fixed claim→policy
    playbook—it walks **any** edge type, so nearby banks, addresses, people, and
    businesses appear when the synthetic graph links them within a few hops.

    **Returns:** ``summary``, ``explanation_plain``, ``evidence_bullets``,
    ``type_counts`` (DataFrame), ``nodes`` (``node_id``, ``node_type``, ``label``,
    ``depth_from_claim``), ``edges`` (directed links with both ends in the slice),
    plus ``claim_node_id`` and ``max_depth`` for UI.
    """
    G = _require_graph()
    if claim_node_id not in G:
        raise KeyError(f"Unknown node_id: {claim_node_id!r}")
    if G.nodes[claim_node_id].get("node_type") != "Claim":
        raise ValueError(f"Node {claim_node_id!r} is not a Claim node")

    dist = _nodes_within_undirected_depth(G, claim_node_id, max_depth)
    involved = frozenset(dist.keys())

    node_rows: list[dict] = []
    for nid in sorted(involved, key=lambda x: (dist[x], x)):
        d = G.nodes[nid]
        node_rows.append(
            {
                "node_id": nid,
                "node_type": d.get("node_type", ""),
                "label": d.get("label", ""),
                "depth_from_claim": dist[nid],
            }
        )
    nodes_df = pd.DataFrame(node_rows)

    edge_rows: list[dict] = []
    for u, v, data in G.edges(data=True):
        if u not in involved or v not in involved:
            continue
        edge_rows.append(
            {
                "from_node": u,
                "to_node": v,
                "edge_type": data.get("edge_type", ""),
                "edge_id": data.get("edge_id", ""),
            }
        )
    edges_df = pd.DataFrame(edge_rows)

    type_counts_map: dict[str, int] = {}
    for nid in involved:
        t = str(G.nodes[nid].get("node_type") or "Unknown")
        type_counts_map[t] = type_counts_map.get(t, 0) + 1
    type_rows = [{"node_type": t, "count": type_counts_map[t]} for t in sorted(type_counts_map, key=lambda k: (-type_counts_map[k], k))]
    type_counts_df = pd.DataFrame(type_rows)

    c_lab = G.nodes[claim_node_id].get("label") or claim_node_id
    depth_word = "hop" if max_depth == 1 else "hops"
    summary = (
        f"Claim {claim_node_id} ({c_lab}): within {max_depth} undirected {depth_word}, "
        f"{len(involved)} nodes, {len(edge_rows)} edges among them."
    )

    parts = [
        f"We started at claim **{c_lab}** (`{claim_node_id}`) and included **every entity** "
        f"reachable in up to **{max_depth} steps** when we treat relationships as a **link chart** "
        "(each edge can be traversed either way for counting distance only—arrows in the data still show "
        "how the record was stored). ",
        f"The neighborhood has **{len(involved)}** entities across **{len(type_counts_map)}** different types. ",
        "Use the **counts by type** table for a quick SIU snapshot, then the **nodes** and **edges** tables "
        "for drill-down. Anything farther than this radius is **out of scope** for this view.",
    ]
    explanation_plain = "".join(parts)

    evidence: list[str] = []
    for _, row in edges_df.head(40).iterrows():
        u, v, et = row["from_node"], row["to_node"], row["edge_type"]
        evidence.append(f"{u} —[{et}]→ {v}")
    if len(edges_df) > 40:
        evidence.append(f"… and {len(edges_df) - 40} more edges in the neighborhood.")

    return {
        "summary": summary,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence,
        "claim_node_id": claim_node_id,
        "max_depth": max_depth,
        "type_counts": type_counts_df,
        "nodes": nodes_df,
        "edges": edges_df,
    }


def find_shared_bank_accounts() -> dict:
    """
    Find **BankAccount** nodes held by **two or more people** (``HOLD_BY``).

    **How it works:** For each bank node, list **predecessors** along ``HOLD_BY``
    (Person → BankAccount in our CSV). Resolve each person’s **latest** ``LOCATED_IN``
    address. Flag whether all holders share one address or **addresses differ**
    (often interesting for non-household sharing).

    **Returns:** dict with ``table`` (DataFrame), ``explanation_plain``, and
    ``evidence_bullets`` (``HOLD_BY`` / ``LOCATED_IN`` links used).
    """
    G = _require_graph()
    rows: list[dict] = []

    for nid, data in G.nodes(data=True):
        if data.get("node_type") != "BankAccount":
            continue
        holders = [
            p
            for p in G.predecessors(nid)
            if G.nodes[p].get("node_type") == "Person"
            and G.edges[p, nid].get("edge_type") == "HOLD_BY"
        ]
        if len(holders) < 2:
            continue

        addr_ids = [_person_address_node(G, h) for h in holders]
        distinct_addrs = sorted({a for a in addr_ids if a is not None})
        n_distinct = len(distinct_addrs)

        holder_info = []
        for h in sorted(holders):
            addr = _person_address_node(G, h)
            lab = G.nodes[h].get("label", "")
            alab = G.nodes[addr].get("label", "") if addr else ""
            holder_info.append(f"{h} ({lab}) @ {addr or 'unknown'} ({alab})")

        if n_distinct <= 1:
            note = "All known holders share the same address (household-style)."
        else:
            note = (
                f"Holders use {n_distinct} different addresses — "
                "often worth reviewing for non-household account sharing."
            )

        rows.append(
            {
                "bank_node_id": nid,
                "bank_label": data.get("label"),
                "num_holders": len(holders),
                "holder_person_ids": ", ".join(sorted(holders)),
                "distinct_address_count": n_distinct,
                "address_node_ids": ", ".join(distinct_addrs) if distinct_addrs else "",
                "holders_detail": " | ".join(holder_info),
                "note": note,
            }
        )

    df = pd.DataFrame(rows)
    evidence: list[str] = []
    for r in rows:
        bid = r["bank_node_id"]
        holders_sorted = sorted(
            [x.strip() for x in str(r["holder_person_ids"]).split(",") if x.strip()]
        )
        for h in holders_sorted:
            evidence.append(f"{h} —[HOLD_BY]→ {bid}")
        for h in holders_sorted:
            addr = _person_address_node(G, h)
            if addr:
                evidence.append(f"{h} —[LOCATED_IN]→ {addr}")

    if df.empty:
        explanation_plain = (
            "No bank account in this graph has **two or more people** linked with "
            "`HOLD_BY`, so there is nothing to compare for shared-account patterns."
        )
    else:
        multi_addr = int((df["distinct_address_count"] > 1).sum())
        explanation_plain = (
            f"Found **{len(df)}** bank account(s) where multiple people are on file "
            "as holders (`HOLD_BY`). "
        )
        if multi_addr:
            explanation_plain += (
                f"**{multi_addr}** of those show holders at **different** mailing "
                "addresses—often worth a quick look for non-household sharing or "
                "payment diversion in a fraud review."
            )
        else:
            explanation_plain += (
                "In this extract, every shared account’s holders map to the **same** "
                "address (household-style), which is usually lower risk."
            )

    return {
        "table": df,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence,
    }


def find_related_people_clusters() -> dict:
    """
    **Family / relationship clusters** from Person→Person edges only.

    **How it works:** Build an **undirected** graph that keeps only edges where
    both endpoints are ``Person`` and the edge type is one of ``IS_SPOUSE_OF``,
    ``IS_RELATED_TO``, ``ACT_ON_BEHALF_OF``, ``HIPAA_AUTHORIZED_ON``, ``DIAGNOSED_BY``
    (v1 seed uses the first two). Take **connected components** — each component is
    a cluster of mutually reachable people through those relationships.

    **Returns:** dict with ``table`` (DataFrame), ``explanation_plain``, and
    ``evidence_bullets`` (person–person ties used).
    """
    G = _require_graph()
    PERSON_EDGE_TYPES = frozenset(
        {
            "IS_SPOUSE_OF",
            "IS_RELATED_TO",
            "ACT_ON_BEHALF_OF",
            "HIPAA_AUTHORIZED_ON",
            "DIAGNOSED_BY",
        }
    )

    U = nx.Graph()
    edge_notes: list[tuple[str, str, str]] = []

    for u, v, edata in G.edges(data=True):
        if G.nodes[u].get("node_type") != "Person" or G.nodes[v].get("node_type") != "Person":
            continue
        et = edata.get("edge_type")
        if et not in PERSON_EDGE_TYPES:
            continue
        U.add_edge(u, v)
        props = _parse_properties_json(edata.get("properties_json"))
        detail = props.get("EDGE_DETAIL") or ""
        dsc = props.get("EDGE_DETAIL_DSC") or ""
        extra = f" ({detail})" if detail else ""
        edge_notes.append((u, v, f"{et}{extra}{' [' + dsc + ']' if dsc else ''}"))

    rows: list[dict] = []
    for i, comp in enumerate(sorted(nx.connected_components(U), key=len, reverse=True), start=1):
        members = sorted(comp)
        labels = [G.nodes[m].get("label", m) for m in members]
        rel_parts = []
        for u, v, note in edge_notes:
            if u in comp and v in comp:
                rel_parts.append(f"{u}->{v}: {note}")
        rows.append(
            {
                "cluster_id": i,
                "cluster_size": len(members),
                "person_node_ids": ", ".join(members),
                "person_labels": " | ".join(labels),
                "relationships": "; ".join(sorted(rel_parts)) if rel_parts else "",
            }
        )

    cols = [
        "cluster_id",
        "cluster_size",
        "person_node_ids",
        "person_labels",
        "relationships",
    ]
    if not rows:
        df = pd.DataFrame(columns=cols)
    else:
        df = pd.DataFrame(rows)

    evidence = [f"{u} ↔ {v} ({note})" for u, v, note in edge_notes]

    if df.empty:
        explanation_plain = (
            "There are **no** spouse/family-style links between people in this graph "
            "extract, so no relationship clusters to show."
        )
    else:
        top = rows[0]["cluster_size"] if rows else 0
        explanation_plain = (
            f"The graph contains **{len(rows)}** separate **family / social cluster(s)** "
            "built only from person-to-person ties (spouse, related-to, etc.). "
            f"The largest cluster has **{top}** people—investigators use this to see "
            "who is in the same network as a claimant or insured without reading every "
            "row manually."
        )

    return {
        "table": df,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence,
    }


def find_business_connection_patterns() -> dict:
    """
    Highlight **business ↔ location ↔ people** patterns.

    **How it works:** For each **Business**, follow ``LOCATED_IN`` to an **Address**.
    Collect every **Person** with ``LOCATED_IN`` to that same address. Emit a row
    when at least one person shares the address (typical PoC pattern: agency or
    provider **colocated** with insureds / claimants).

    **Returns:** dict with ``table`` (DataFrame), ``explanation_plain``, and
    ``evidence_bullets`` (shared-address ``LOCATED_IN`` links).
    """
    G = _require_graph()
    rows: list[dict] = []

    for bid, bdata in G.nodes(data=True):
        if bdata.get("node_type") != "Business":
            continue
        addr_ids = [
            v
            for v in G.successors(bid)
            if G.edges[bid, v].get("edge_type") == "LOCATED_IN"
            and G.nodes[v].get("node_type") == "Address"
        ]
        for aid in addr_ids:
            people = [
                p
                for p in G.predecessors(aid)
                if G.nodes[p].get("node_type") == "Person"
                and G.edges[p, aid].get("edge_type") == "LOCATED_IN"
            ]
            if not people:
                continue
            alab = G.nodes[aid].get("label", aid)
            pattern = (
                f"Business '{bdata.get('label')}' shares address '{alab}' "
                f"with {len(people)} person(s)."
            )
            rows.append(
                {
                    "business_node_id": bid,
                    "business_label": bdata.get("label"),
                    "address_node_id": aid,
                    "address_label": alab,
                    "num_people_at_address": len(people),
                    "person_node_ids": ", ".join(sorted(people)),
                    "person_labels": " | ".join(G.nodes[p].get("label", p) for p in sorted(people)),
                    "pattern": pattern,
                }
            )

    df = pd.DataFrame(rows)
    evidence: list[str] = []
    for r in rows:
        bid, aid = r["business_node_id"], r["address_node_id"]
        evidence.append(f"{bid} —[LOCATED_IN]→ {aid}")
        for p in str(r["person_node_ids"]).split(","):
            ps = p.strip()
            if ps:
                evidence.append(f"{ps} —[LOCATED_IN]→ {aid}")

    if df.empty:
        explanation_plain = (
            "No **business** shares a **street address** with a **person** in this "
            "extract (`LOCATED_IN` to the same address), so there is no colocation "
            "pattern to flag here."
        )
    else:
        explanation_plain = (
            f"Found **{len(df)}** place(s) where a **business** is registered at the "
            "**same address** as one or more **people** in the graph. In SIU demos "
            "this often prompts a look at related-party care, home-based agencies, "
            "or address reuse—even when the link is innocent."
        )

    return {
        "table": df,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence,
    }


def _print_section(title: str, explanation: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n{title}\n{bar}")
    print(explanation.strip() + "\n")


def main() -> None:
    """
    Load the synthetic PoC graph and demonstrate investigation-oriented queries.

    Each block prints a short **how it works** blurb, then tabular output.
    """
    print("Loading graph from CSV...")
    load_graph()
    G = _require_graph()
    print(f"Loaded {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")

    _print_section(
        "summarize_graph()",
        "Counts nodes and edges, and tallies node_type / edge_type frequencies. "
        "Use this as a quick health check after running build_graph_files.py.",
    )
    pprint(summarize_graph())

    demo_claim = "claim_C9000000002"
    _print_section(
        f'get_claim_network("{demo_claim}")',
        "Starts at a Claim, walks to its Policy, lists other claims on that policy, "
        "lists every Person tied to the policy (insured or agent), and matches the "
        "claim’s claimant fields to a Person node when names and birth date align.",
    )
    net = get_claim_network(demo_claim)
    print(net["summary"])
    print("\n" + net["explanation_plain"])
    print("\nSupporting links:")
    for line in net["evidence_bullets"]:
        print(f"  • {line}")
    for key in (
        "claim",
        "linked_policies",
        "other_claims_on_policy",
        "people_linked_to_policy",
        "claimant_person_match",
    ):
        print(f"\n--- {key} ---")
        df = net[key]
        if isinstance(df, pd.DataFrame):
            if df.empty:
                print("(empty DataFrame)")
            else:
                # Wide tables: show all columns; wrap by pandas display
                with pd.option_context("display.max_columns", None, "display.width", 120):
                    print(df.to_string(index=False))
        else:
            print(df)

    _print_section(
        f'get_claim_subgraph_summary("{demo_claim}", max_depth=2)',
        "Undirected BFS from the Claim: all entities within max_depth steps, with "
        "counts by type plus node/edge tables (broader than get_claim_network).",
    )
    sub = get_claim_subgraph_summary(demo_claim, max_depth=2)
    print(sub["summary"])
    print("\n" + sub["explanation_plain"])
    print("\nType counts:")
    print(sub["type_counts"].to_string(index=False))
    print(f"\nNodes ({len(sub['nodes'])} rows), edges ({len(sub['edges'])} rows) — see DataFrames in code.")

    _print_section(
        "find_shared_bank_accounts()",
        "Groups Person→BankAccount HOLD_BY edges by bank. Reports only banks with "
        "two or more holders, resolves each holder’s LOCATED_IN address, and flags "
        "when holders map to multiple addresses.",
    )
    shared = find_shared_bank_accounts()
    print(shared["explanation_plain"])
    for line in shared["evidence_bullets"][:12]:
        print(f"  • {line}")
    if len(shared["evidence_bullets"]) > 12:
        print(f"  • … ({len(shared['evidence_bullets']) - 12} more lines)")
    sb_df = shared["table"]
    if sb_df.empty:
        print("(no bank with 2+ holders)")
    else:
        with pd.option_context("display.max_columns", None, "display.width", 120):
            print(sb_df.to_string(index=False))

    _print_section(
        "find_related_people_clusters()",
        "Builds an undirected subgraph on Person–Person edges (spouse, related-to, etc.) "
        "and splits it into connected components. Each row is one family/social cluster.",
    )
    clusters = find_related_people_clusters()
    print(clusters["explanation_plain"])
    for line in clusters["evidence_bullets"][:8]:
        print(f"  • {line}")
    cdf = clusters["table"]
    if cdf.empty:
        print("(no person–person edges)")
    else:
        with pd.option_context("display.max_columns", None, "display.width", 120):
            print(cdf.to_string(index=False))

    _print_section(
        "find_business_connection_patterns()",
        "For each Business, finds its Address via LOCATED_IN, then lists every Person "
        "at that address. Surfaces colocation of providers/agencies with parties.",
    )
    biz = find_business_connection_patterns()
    print(biz["explanation_plain"])
    for line in biz["evidence_bullets"][:12]:
        print(f"  • {line}")
    if len(biz["evidence_bullets"]) > 12:
        print(f"  • … ({len(biz['evidence_bullets']) - 12} more lines)")
    bdf = biz["table"]
    if bdf.empty:
        print("(no business/person colocation)")
    else:
        with pd.option_context("display.max_columns", None, "display.width", 120):
            print(bdf.to_string(index=False))

    print("\n" + "=" * 72)
    print("Done. Import this module and call load_graph() before using the helpers.")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
