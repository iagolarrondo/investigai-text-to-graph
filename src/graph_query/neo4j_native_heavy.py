"""
Neo4j Cypher implementations for composite investigation tools (claim/policy/subgraph/patterns).

Imported only when ``NEO4J_READ_MODE=native``; pairs with :mod:`neo4j_native_reads` for primitives.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
import pandas as pd

from src.graph_query.neo4j_native_reads import parse_properties_json
from src.graph_store.neo4j_read_session import run_read_query as rq

# Mirrors ``query_graph.PERSON_TO_PERSON_RELATIONSHIP_TYPES``
PERSON_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "IS_SPOUSE_OF",
        "IS_RELATED_TO",
        "ACT_ON_BEHALF_OF",
        "HIPAA_AUTHORIZED_ON",
        "DIAGNOSED_BY",
    }
)


def _chunked(xs: list[Any], size: int):
    for i in range(0, len(xs), size):
        yield xs[i : i + size]


def _require_entity_type(node_id: str, expected: str) -> None:
    rows = rq("MATCH (n:Entity {node_id: $id}) RETURN n.node_type AS nt", {"id": node_id})
    if not rows:
        raise KeyError(f"Unknown node_id: {node_id!r}")
    if str(rows[0].get("nt") or "") != expected:
        raise ValueError(f"Node {node_id!r} is not a {expected} node")


def _node_row_from_store(nid: str, attrs: dict[str, Any]) -> dict[str, Any]:
    pj = attrs.get("properties_json")
    props = parse_properties_json(pj)
    return {
        "node_id": nid,
        "label": attrs.get("label"),
        "node_type": attrs.get("node_type"),
        "properties_json": pj,
        "parsed_props": props,
    }


def _fetch_nodes_bulk(node_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for chunk in _chunked(list(dict.fromkeys(node_ids)), 600):
        rows = rq(
            """
            MATCH (n:Entity)
            WHERE n.node_id IN $ids
            RETURN n.node_id AS nid, n.node_type AS nt, n.label AS lab, n.properties_json AS pj
            """,
            {"ids": chunk},
        )
        for r in rows:
            nid = str(r["nid"])
            out[nid] = {"node_type": r["nt"], "label": r["lab"], "properties_json": r["pj"]}
    return out


def _undirected_ball(
    anchor_id: str,
    max_depth: int,
    *,
    expected_type: str | None = None,
) -> tuple[dict[str, int], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """BFS neighbourhood around ``anchor_id`` up to ``max_depth`` undirected hops.

    Returns ``(dist, attrs, edges)``. Node attributes are fetched in the same
    round-trip as distances — no separate ``_fetch_nodes_bulk`` call needed.

    If ``expected_type`` is given, raises ``ValueError`` when the anchor's
    ``node_type`` doesn't match (replaces the separate ``_require_entity_type`` query).
    """
    cap = min(max(1, max_depth), 25)
    # Combined: distances + node attributes in one query (eliminates _fetch_nodes_bulk call).
    q = f"""
    MATCH (s:Entity {{node_id: $aid}})
    MATCH p = (s)-[:GRAPH_EDGE*0..{cap}]-(n:Entity)
    WITH n, min(length(p)) AS d
    WHERE d <= $depth
    RETURN n.node_id AS nid, d,
           n.node_type AS nt, n.label AS lab, n.properties_json AS pj
    """
    rows = rq(q, {"aid": anchor_id, "depth": max_depth})
    if not rows:
        raise KeyError(f"Unknown node_id: {anchor_id!r}")
    dist: dict[str, int] = {}
    attrs: dict[str, dict[str, Any]] = {}
    for r in rows:
        nid = str(r["nid"])
        dist[nid] = int(r["d"])
        attrs[nid] = {"node_type": r["nt"], "label": r["lab"], "properties_json": r["pj"]}
    if expected_type:
        actual = str(attrs.get(anchor_id, {}).get("node_type") or "")
        if actual != expected_type:
            raise ValueError(f"Node {anchor_id!r} is not a {expected_type} node (got {actual!r})")
    nids = list(dist.keys())
    edges_raw: list[dict[str, Any]] = []
    for chunk in _chunked(nids, 500):
        edges_raw.extend(
            rq(
                """
                MATCH (a:Entity)-[r:GRAPH_EDGE]->(b:Entity)
                WHERE a.node_id IN $ids AND b.node_id IN $ids
                RETURN a.node_id AS u, b.node_id AS v, r.edge_type AS edge_type, r.edge_id AS edge_id
                """,
                {"ids": chunk},
            )
        )
    seen_e: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for e in edges_raw:
        t = (str(e["u"]), str(e["v"]), str(e.get("edge_type") or ""), str(e.get("edge_id") or ""))
        if t in seen_e:
            continue
        seen_e.add(t)
        deduped.append({"from_node": t[0], "to_node": t[1], "edge_type": t[2], "edge_id": t[3]})
    return dist, attrs, deduped


def get_claim_subgraph_summary(claim_node_id: str, max_depth: int = 2) -> dict[str, Any]:
    dist, attrs, edge_rows = _undirected_ball(claim_node_id, max_depth, expected_type="Claim")
    involved = frozenset(dist.keys())
    node_rows = []
    for nid in sorted(involved, key=lambda x: (dist[x], x)):
        a = attrs[nid]
        node_rows.append(
            {
                "node_id": nid,
                "node_type": a.get("node_type", ""),
                "label": a.get("label", ""),
                "depth_from_claim": dist[nid],
            }
        )
    nodes_df = pd.DataFrame(node_rows)
    edges_df = pd.DataFrame(edge_rows)
    type_counts_map: dict[str, int] = {}
    for nid in involved:
        t = str(attrs[nid].get("node_type") or "Unknown")
        type_counts_map[t] = type_counts_map.get(t, 0) + 1
    type_rows = [
        {"node_type": t, "count": type_counts_map[t]}
        for t in sorted(type_counts_map, key=lambda k: (-type_counts_map[k], k))
    ]
    type_counts_df = pd.DataFrame(type_rows)
    c_lab = attrs[claim_node_id].get("label") or claim_node_id
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
        evidence.append(f"{row['from_node']} —[{row['edge_type']}]→ {row['to_node']}")
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


def get_person_subgraph_summary(person_node_id: str, max_depth: int = 2) -> dict[str, Any]:
    dist, attrs, edge_rows = _undirected_ball(person_node_id, max_depth, expected_type="Person")
    involved = frozenset(dist.keys())
    node_rows = []
    for nid in sorted(involved, key=lambda x: (dist[x], x)):
        a = attrs[nid]
        node_rows.append(
            {
                "node_id": nid,
                "node_type": a.get("node_type", ""),
                "label": a.get("label", ""),
                "depth_from_person": dist[nid],
            }
        )
    nodes_df = pd.DataFrame(node_rows)
    edges_df = pd.DataFrame(edge_rows)
    type_counts_map: dict[str, int] = {}
    for nid in involved:
        t = str(attrs[nid].get("node_type") or "Unknown")
        type_counts_map[t] = type_counts_map.get(t, 0) + 1
    type_rows = [
        {"node_type": t, "count": type_counts_map[t]}
        for t in sorted(type_counts_map, key=lambda k: (-type_counts_map[k], k))
    ]
    type_counts_df = pd.DataFrame(type_rows)
    p_lab = attrs[person_node_id].get("label") or person_node_id
    depth_word = "hop" if max_depth == 1 else "hops"
    summary = (
        f"Person {person_node_id} ({p_lab}): within {max_depth} undirected {depth_word}, "
        f"{len(involved)} nodes, {len(edge_rows)} edges among them."
    )
    explanation_plain = (
        f"We started at person **{p_lab}** (`{person_node_id}`) and included **every entity** "
        f"reachable in up to **{max_depth} undirected step(s)** on the link chart (same distance "
        "rule as the claim neighborhood view). "
        f"The slice has **{len(involved)}** entities across **{len(type_counts_map)}** types."
    )
    evidence: list[str] = []
    for _, row in edges_df.head(40).iterrows():
        evidence.append(f"{row['from_node']} —[{row['edge_type']}]→ {row['to_node']}")
    if len(edges_df) > 40:
        evidence.append(f"… and {len(edges_df) - 40} more edges in the neighborhood.")
    return {
        "summary": summary,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence,
        "person_node_id": person_node_id,
        "max_depth": max_depth,
        "type_counts": type_counts_df,
        "nodes": nodes_df,
        "edges": edges_df,
    }


def get_policy_network(policy_node_id: str) -> dict[str, Any]:
    _require_entity_type(policy_node_id, "Policy")
    pid = policy_node_id
    prow = rq(
        "MATCH (n:Entity {node_id: $id}) RETURN n.label AS lab, n.properties_json AS pj",
        {"id": pid},
    )[0]
    pprops = parse_properties_json(prow["pj"])
    policy_df = pd.DataFrame(
        [
            {
                "policy_node_id": pid,
                "label": prow.get("lab"),
                "POLICY_NUMBER": pprops.get("POLICY_NUMBER"),
                "POLICY_STATUS": pprops.get("POLICY_STATUS"),
            }
        ]
    )
    people_rows = rq(
        """
        MATCH (per:Entity)-[r:GRAPH_EDGE]->(pol:Entity {node_id: $pid})
        WHERE per.node_type = 'Person'
          AND pol.node_type = 'Policy'
          AND r.edge_type IN ['IS_COVERED_BY', 'SOLD_POLICY']
        RETURN per.node_id AS person_node_id, per.label AS person_label,
               r.edge_type AS relationship_to_policy,
               r.properties_json AS ej
        """,
        {"pid": pid},
    )
    people_on_policy = pd.DataFrame(
        [
            {
                "person_node_id": str(r["person_node_id"]),
                "person_label": r.get("person_label"),
                "relationship_to_policy": str(r["relationship_to_policy"]),
                "EDGE_DETAIL": parse_properties_json(r.get("ej")).get("EDGE_DETAIL"),
            }
            for r in people_rows
        ]
    )
    claim_rows_raw = rq(
        """
        MATCH (cl:Entity)-[r:GRAPH_EDGE]->(pol:Entity {node_id: $pid})
        WHERE cl.node_type = 'Claim' AND r.edge_type = 'IS_CLAIM_AGAINST_POLICY'
        RETURN cl.node_id AS claim_node_id, cl.label AS label, cl.properties_json AS pj
        """,
        {"pid": pid},
    )
    claim_rows = []
    for r in claim_rows_raw:
        cp = parse_properties_json(r.get("pj"))
        claim_rows.append(
            {
                "claim_node_id": str(r["claim_node_id"]),
                "label": r.get("label"),
                "CLAIM_NUMBER": cp.get("CLAIM_NUMBER"),
                "CLAIM_STATUS_CODE": cp.get("CLAIM_STATUS_CODE"),
            }
        )
    claims_on_policy = pd.DataFrame(claim_rows)
    summary = (
        f"Policy {pid}: {len(people_rows)} person–policy link(s), {len(claim_rows)} claim(s) "
        "filed against this policy."
    )
    explanation_plain = (
        f"Policy **`{pprops.get('POLICY_NUMBER') or pid}`** (`{pid}`): tables list **every person** "
        "with `IS_COVERED_BY` or `SOLD_POLICY` to this policy, and **every claim** with "
        "`IS_CLAIM_AGAINST_POLICY` into it."
    )
    evidence: list[str] = []
    for _, r in people_on_policy.iterrows():
        evidence.append(f"{r['person_node_id']} —[{r['relationship_to_policy']}]→ {pid}")
    for _, r in claims_on_policy.iterrows():
        evidence.append(f"{r['claim_node_id']} —[IS_CLAIM_AGAINST_POLICY]→ {pid}")
    return {
        "summary": summary,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence,
        "policy_node_id": pid,
        "policy": policy_df,
        "people_on_policy": people_on_policy,
        "claims_on_policy": claims_on_policy,
    }


def _person_address_native(person_id: str) -> str | None:
    rows = rq(
        """
        MATCH (p:Entity {node_id: $pid})-[r:GRAPH_EDGE]->(a:Entity)
        WHERE p.node_type = 'Person' AND a.node_type = 'Address' AND r.edge_type = 'LOCATED_IN'
        RETURN a.node_id AS aid LIMIT 1
        """,
        {"pid": person_id},
    )
    return str(rows[0]["aid"]) if rows else None


def find_shared_bank_accounts() -> dict[str, Any]:
    holders_raw = rq(
        """
        MATCH (p:Entity)-[r:GRAPH_EDGE]->(b:Entity)
        WHERE p.node_type = 'Person' AND b.node_type = 'BankAccount' AND r.edge_type = 'HOLD_BY'
        RETURN b.node_id AS bid, b.label AS blab, collect(DISTINCT p.node_id) AS holders
        """
    )
    # Collect all unique holder person IDs across all shared accounts.
    all_holder_ids: list[str] = []
    shared: list[dict[str, Any]] = []
    for r in holders_raw:
        holders = [str(x) for x in (r["holders"] or [])]
        if len(holders) >= 2:
            shared.append(r)
            all_holder_ids.extend(holders)

    # Batch: fetch each person's address in one query instead of N individual queries.
    person_to_addr: dict[str, str | None] = {}
    if all_holder_ids:
        addr_rows = rq(
            """
            MATCH (p:Entity)-[r:GRAPH_EDGE]->(a:Entity)
            WHERE p.node_id IN $pids
              AND p.node_type = 'Person'
              AND a.node_type = 'Address'
              AND r.edge_type = 'LOCATED_IN'
            RETURN p.node_id AS pid, a.node_id AS aid
            """,
            {"pids": list(dict.fromkeys(all_holder_ids))},
        )
        for ar in addr_rows:
            person_to_addr[str(ar["pid"])] = str(ar["aid"])

    # Collect all node IDs we need labels for in one bulk fetch.
    nodes_needed: list[str] = []
    for r in shared:
        holders = [str(x) for x in (r["holders"] or [])]
        nodes_needed.append(str(r["bid"]))
        nodes_needed.extend(holders)
        for h in holders:
            addr = person_to_addr.get(h)
            if addr:
                nodes_needed.append(addr)
    attrs = _fetch_nodes_bulk(nodes_needed) if nodes_needed else {}

    rows: list[dict[str, Any]] = []
    for r in shared:
        holders = sorted(str(x) for x in (r["holders"] or []))
        bid = str(r["bid"])
        addr_ids = [person_to_addr.get(h) for h in holders]
        distinct_addrs = sorted({a for a in addr_ids if a is not None})
        n_distinct = len(distinct_addrs)
        holder_info = []
        for h in holders:
            addr = person_to_addr.get(h)
            lab = attrs.get(h, {}).get("label", "")
            alab = attrs.get(addr, {}).get("label", "") if addr else ""
            holder_info.append(f"{h} ({lab}) @ {addr or 'unknown'} ({alab})")
        note = (
            "All known holders share the same address (household-style)."
            if n_distinct <= 1
            else (
                f"Holders use {n_distinct} different addresses — "
                "often worth reviewing for non-household account sharing."
            )
        )
        rows.append(
            {
                "bank_node_id": bid,
                "bank_label": r.get("blab"),
                "num_holders": len(holders),
                "holder_person_ids": ", ".join(holders),
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
        holders_sorted = [x.strip() for x in str(r["holder_person_ids"]).split(",") if x.strip()]
        for h in holders_sorted:
            evidence.append(f"{h} —[HOLD_BY]→ {bid}")
        for h in holders_sorted:
            addr = person_to_addr.get(h)
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
    return {"table": df, "explanation_plain": explanation_plain, "evidence_bullets": evidence}


def find_related_people_clusters() -> dict[str, Any]:
    types = list(PERSON_EDGE_TYPES)
    edges_raw = rq(
        """
        MATCH (a:Entity)-[r:GRAPH_EDGE]-(b:Entity)
        WHERE a.node_type = 'Person' AND b.node_type = 'Person'
          AND a.node_id < b.node_id
          AND r.edge_type IN $types
        RETURN a.node_id AS u, b.node_id AS v, r.edge_type AS et, r.properties_json AS pj
        """,
        {"types": types},
    )
    U = nx.Graph()
    edge_notes: list[tuple[str, str, str]] = []
    attrs_needed: set[str] = set()
    for r in edges_raw:
        u, v = str(r["u"]), str(r["v"])
        U.add_edge(u, v)
        attrs_needed.add(u)
        attrs_needed.add(v)
        props = parse_properties_json(r.get("pj"))
        detail = props.get("EDGE_DETAIL") or ""
        dsc = props.get("EDGE_DETAIL_DSC") or ""
        extra = f" ({detail})" if detail else ""
        note = f"{r['et']}{extra}{' [' + dsc + ']' if dsc else ''}"
        edge_notes.append((u, v, note))
    attrs = _fetch_nodes_bulk(list(attrs_needed))
    rows_out: list[dict[str, Any]] = []
    for i, comp in enumerate(sorted(nx.connected_components(U), key=len, reverse=True), start=1):
        members = sorted(comp)
        labels = [attrs.get(m, {}).get("label", m) for m in members]
        rel_parts = []
        for u, v, note in edge_notes:
            if u in comp and v in comp:
                rel_parts.append(f"{u}->{v}: {note}")
        rows_out.append(
            {
                "cluster_id": i,
                "cluster_size": len(members),
                "person_node_ids": ", ".join(members),
                "person_labels": " | ".join(str(lab) for lab in labels),
                "relationships": "; ".join(sorted(rel_parts)) if rel_parts else "",
            }
        )
    cols = ["cluster_id", "cluster_size", "person_node_ids", "person_labels", "relationships"]
    df = pd.DataFrame(rows_out, columns=cols) if rows_out else pd.DataFrame(columns=cols)
    evidence = [f"{u} ↔ {v} ({note})" for u, v, note in edge_notes]
    if df.empty:
        explanation_plain = (
            "There are **no** spouse/family-style links between people in this graph "
            "extract, so no relationship clusters to show."
        )
    else:
        top = rows_out[0]["cluster_size"] if rows_out else 0
        explanation_plain = (
            f"The graph contains **{len(rows_out)}** separate **family / social cluster(s)** "
            "built only from person-to-person ties (spouse, related-to, etc.). "
            f"The largest cluster has **{top}** people—investigators use this to see "
            "who is in the same network as a claimant or insured without reading every "
            "row manually."
        )
    return {"table": df, "explanation_plain": explanation_plain, "evidence_bullets": evidence}


def find_business_connection_patterns() -> dict[str, Any]:
    raw = rq(
        """
        MATCH (biz:Entity)-[rb:GRAPH_EDGE]->(addr:Entity)
        WHERE biz.node_type = 'Business' AND addr.node_type = 'Address' AND rb.edge_type = 'LOCATED_IN'
        MATCH (p:Entity)-[rp:GRAPH_EDGE]->(addr)
        WHERE p.node_type = 'Person' AND rp.edge_type = 'LOCATED_IN'
        RETURN biz.node_id AS bid, biz.label AS blab, addr.node_id AS aid, addr.label AS alab,
               collect(DISTINCT p.node_id) AS pids
        """
    )
    rows: list[dict[str, Any]] = []
    attrs = _fetch_nodes_bulk(
        [str(r["bid"]) for r in raw] + [str(r["aid"]) for r in raw] + [str(p) for r in raw for p in (r["pids"] or [])]
    )
    for r in raw:
        people = sorted(str(x) for x in (r["pids"] or []))
        if not people:
            continue
        bid, aid = str(r["bid"]), str(r["aid"])
        alab = r.get("alab") or aid
        pattern = (
            f"Business '{r.get('blab')}' shares address '{alab}' "
            f"with {len(people)} person(s)."
        )
        rows.append(
            {
                "business_node_id": bid,
                "business_label": r.get("blab"),
                "address_node_id": aid,
                "address_label": alab,
                "num_people_at_address": len(people),
                "person_node_ids": ", ".join(people),
                "person_labels": " | ".join(attrs.get(p, {}).get("label", p) for p in people),
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
    return {"table": df, "explanation_plain": explanation_plain, "evidence_bullets": evidence}


def _collect_people_linked_to_claim_native(claim_node_id: str) -> list[dict[str, Any]]:
    cid = claim_node_id
    pids: set[str] = set()
    direct_out = rq(
        """
        MATCH (c:Entity {node_id: $cid})-[r:GRAPH_EDGE]->(p:Entity)
        WHERE p.node_type = 'Person'
        RETURN p.node_id AS pid, r.edge_type AS et
        """,
        {"cid": cid},
    )
    direct_in = rq(
        """
        MATCH (p:Entity)-[r:GRAPH_EDGE]->(c:Entity {node_id: $cid})
        WHERE p.node_type = 'Person'
        RETURN p.node_id AS pid, r.edge_type AS et
        """,
        {"cid": cid},
    )
    twohop = rq(
        """
        MATCH (c:Entity {node_id: $cid})-[r1:GRAPH_EDGE]-(mid:Entity)-[r2:GRAPH_EDGE]-(p:Entity)
        WHERE mid.node_type <> 'Policy' AND p.node_type = 'Person'
          AND p.node_id <> $cid
        RETURN DISTINCT p.node_id AS pid, mid.node_id AS mid, mid.node_type AS midt, r2.edge_type AS et2
        """,
        {"cid": cid},
    )
    for block in (direct_out, direct_in, twohop):
        for r in block:
            pids.add(str(r["pid"]))
    attrs_map = _fetch_nodes_bulk([cid] + list(pids))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(pid: str, **kw: Any) -> None:
        if pid in seen:
            return
        seen.add(pid)
        d = _node_row_from_store(pid, attrs_map[pid])
        rows.append({"person_node_id": pid, "person_label": d.get("label"), **kw})

    for r in direct_out:
        _add(
            str(r["pid"]),
            path_type="direct",
            summary=f"{cid} —[{r['et']}]→ {r['pid']}",
            via_intermediate_node="",
            via_intermediate_type="",
        )
    for r in direct_in:
        _add(
            str(r["pid"]),
            path_type="direct",
            summary=f"{r['pid']} —[{r['et']}]→ {cid}",
            via_intermediate_node="",
            via_intermediate_type="",
        )
    for r in twohop:
        pid = str(r["pid"])
        if pid in seen:
            continue
        mid = str(r["mid"])
        mid_type = str(r.get("midt") or "Unknown")
        et2 = str(r.get("et2") or "")
        _add(
            pid,
            path_type="via_intermediate",
            summary=(
                f"{cid} ↔ {mid} ({mid_type}) —[{et2}]→ {pid} "
                f"(two-hop; not via policy-only path)"
            ),
            via_intermediate_node=mid,
            via_intermediate_type=mid_type,
        )
    return rows


def get_claim_network(claim_node_id: str) -> dict[str, Any]:
    from src.graph_query.query_graph import _narrate_claim_network

    cid = claim_node_id
    # Merged: type validation + claim row in one query.
    crow_rows = rq(
        "MATCH (c:Entity {node_id: $id}) RETURN c.node_type AS nt, c.label AS lab, c.properties_json AS pj",
        {"id": cid},
    )
    if not crow_rows:
        raise KeyError(f"Unknown node_id: {cid!r}")
    if str(crow_rows[0].get("nt") or "") != "Claim":
        raise ValueError(f"Node {cid!r} is not a Claim node")
    crow = crow_rows[0]
    cprops = parse_properties_json(crow["pj"])
    claim_df = pd.DataFrame(
        [
            {
                "node_id": cid,
                "label": crow.get("lab"),
                "CLAIM_NUMBER": cprops.get("CLAIM_NUMBER"),
                "POLICY_NUMBER": cprops.get("POLICY_NUMBER"),
                "CLAIM_STATUS_CODE": cprops.get("CLAIM_STATUS_CODE"),
                "claimant_FIRST_NAME": cprops.get("FIRST_NAME"),
                "claimant_LAST_NAME": cprops.get("LAST_NAME"),
                "claimant_BIRTH_DATE": cprops.get("BIRTH_DATE"),
            }
        ]
    )
    policy_ids = [
        str(r["pid"])
        for r in rq(
            """
            MATCH (c:Entity {node_id: $cid})-[r:GRAPH_EDGE]->(pol:Entity)
            WHERE r.edge_type = 'IS_CLAIM_AGAINST_POLICY' AND pol.node_type = 'Policy'
            RETURN pol.node_id AS pid
            """,
            {"cid": cid},
        )
    ]
    attrs_map: dict[str, dict[str, Any]] = _fetch_nodes_bulk([cid] + policy_ids)
    pol_rows = []
    for pid in policy_ids:
        d = _node_row_from_store(pid, attrs_map[pid])
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
    other_claim_rows: list[dict[str, Any]] = []
    for pid in policy_ids:
        for r in rq(
            """
            MATCH (c2:Entity)-[r:GRAPH_EDGE]->(pol:Entity {node_id: $pid})
            WHERE c2.node_type = 'Claim' AND r.edge_type = 'IS_CLAIM_AGAINST_POLICY'
              AND c2.node_id <> $cid
            RETURN c2.node_id AS pred, c2.label AS lab, c2.properties_json AS pj
            """,
            {"pid": pid, "cid": cid},
        ):
            p = parse_properties_json(r["pj"])
            other_claim_rows.append(
                {
                    "claim_node_id": str(r["pred"]),
                    "label": r.get("lab"),
                    "CLAIM_NUMBER": p.get("CLAIM_NUMBER"),
                    "CLAIM_STATUS_CODE": p.get("CLAIM_STATUS_CODE"),
                    "claimant_FIRST_NAME": p.get("FIRST_NAME"),
                    "claimant_LAST_NAME": p.get("LAST_NAME"),
                    "shared_policy_node_id": pid,
                }
            )
    other_claims = pd.DataFrame(other_claim_rows)
    party_rows: list[dict[str, Any]] = []
    for pid in policy_ids:
        for r in rq(
            """
            MATCH (per:Entity)-[r:GRAPH_EDGE]->(pol:Entity {node_id: $pid})
            WHERE per.node_type = 'Person'
              AND r.edge_type IN ['IS_COVERED_BY', 'SOLD_POLICY']
            RETURN per.node_id AS pred, per.label AS plab, r.edge_type AS et, r.properties_json AS ej
            """,
            {"pid": pid},
        ):
            party_rows.append(
                {
                    "person_node_id": str(r["pred"]),
                    "person_label": r.get("plab"),
                    "relationship_to_policy": str(r["et"]),
                    "policy_node_id": pid,
                    "EDGE_DETAIL": parse_properties_json(r.get("ej")).get("EDGE_DETAIL"),
                }
            )
    people_on_policy = pd.DataFrame(party_rows)
    fn = (cprops.get("FIRST_NAME") or "").strip().upper()
    ln = (cprops.get("LAST_NAME") or "").strip().upper()
    bd = str(cprops.get("BIRTH_DATE") or "").strip()
    match_rows: list[dict[str, Any]] = []
    persons_raw = rq(
        "MATCH (p:Entity {node_type: 'Person'}) RETURN p.node_id AS id, p.label AS lab, p.properties_json AS pj"
    )
    for r in persons_raw:
        p = parse_properties_json(r["pj"])
        pfn = (str(p.get("FIRST_NAME") or "")).strip().upper()
        pln = (str(p.get("LAST_NAME") or "")).strip().upper()
        pbd = str(p.get("BIRTH_DATE") or "").strip()
        if fn and ln and pfn == fn and pln == ln and (not bd or not pbd or bd[:10] == pbd[:10]):
            match_rows.append(
                {
                    "person_node_id": str(r["id"]),
                    "person_label": r.get("lab"),
                    "FIRST_NAME": p.get("FIRST_NAME"),
                    "LAST_NAME": p.get("LAST_NAME"),
                    "BIRTH_DATE": p.get("BIRTH_DATE"),
                }
            )
    claimant_match = pd.DataFrame(match_rows)
    claim_people_rows = _collect_people_linked_to_claim_native(cid)
    people_on_claim = pd.DataFrame(claim_people_rows)
    summary = (
        f"Claim {cid}: {len(policy_ids)} linked polic(y/ies), "
        f"{len(other_claim_rows)} other claim(s) on same policy, "
        f"{len(party_rows)} person–policy link(s), "
        f"{len(claim_people_rows)} person(s) linked to the claim (direct or via non-policy), "
        f"{len(match_rows)} claimant→person match(es)."
    )
    explanation_plain, evidence_bullets = _narrate_claim_network(
        claim_node_id=cid,
        policy_ids=policy_ids,
        claim_number=str(cprops.get("CLAIM_NUMBER") or cid),
        num_other_claims=len(other_claim_rows),
        other_claim_rows=other_claim_rows,
        party_rows=party_rows,
        match_rows=match_rows,
        claim_people_rows=claim_people_rows,
    )
    return {
        "summary": summary,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence_bullets,
        "claim": claim_df,
        "linked_policies": linked_policies,
        "other_claims_on_policy": other_claims,
        "people_linked_to_claim": people_on_claim,
        "people_linked_to_policy": people_on_policy,
        "claimant_person_match": claimant_match,
    }


def policies_with_related_coparties(person_node_id: str) -> dict[str, Any]:
    anchor = (person_node_id or "").strip()
    # Merged: type validation + label fetch in one query.
    anchor_rows = rq(
        "MATCH (p:Entity {node_id: $id}) RETURN p.node_type AS nt, p.label AS lab",
        {"id": anchor},
    )
    if not anchor_rows:
        raise KeyError(f"Unknown node_id: {anchor!r}")
    if str(anchor_rows[0].get("nt") or "") != "Person":
        raise ValueError(f"Node {anchor!r} is not a Person node")
    plab = anchor_rows[0].get("lab") or anchor
    related_lines: dict[str, list[str]] = {}
    rel_raw = rq(
        """
        MATCH (anchor:Entity {node_id: $anchor})-[r:GRAPH_EDGE]-(b:Entity)
        WHERE b.node_type = 'Person' AND b.node_id <> $anchor AND r.edge_type IN $types
        RETURN b.node_id AS oid, r.edge_type AS et, startNode(r).node_id AS sn
        """,
        {"anchor": anchor, "types": list(PERSON_EDGE_TYPES)},
    )
    for r in rel_raw:
        oid = str(r["oid"])
        et = str(r["et"])
        sn = str(r["sn"])
        line = f"{anchor} —[{et}]→ {oid}" if sn == anchor else f"{oid} —[{et}]→ {anchor}"
        related_lines.setdefault(oid, []).append(line)
    policy_roles: dict[str, list[tuple[str, str]]] = {}
    for r in rq(
        """
        MATCH (anchor:Entity {node_id: $aid})-[r:GRAPH_EDGE]->(pol:Entity)
        WHERE anchor.node_type = 'Person' AND pol.node_type = 'Policy'
          AND r.edge_type IN ['IS_COVERED_BY', 'SOLD_POLICY']
        RETURN pol.node_id AS pid, r.edge_type AS et
        """,
        {"aid": anchor},
    ):
        pid = str(r["pid"])
        policy_roles.setdefault(pid, []).append((anchor, str(r["et"])))
    out_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    attrs_pol = _fetch_nodes_bulk(list(policy_roles.keys()))
    pid_coparties: dict[str, list[tuple[str, str]]] = {}
    others_needed: set[str] = set()
    for pid in policy_roles:
        coparty_raw = rq(
            """
            MATCH (per:Entity)-[r:GRAPH_EDGE]->(pol:Entity {node_id: $pid})
            WHERE per.node_type = 'Person'
              AND r.edge_type IN ['IS_COVERED_BY', 'SOLD_POLICY']
            RETURN per.node_id AS pred, r.edge_type AS et
            """,
            {"pid": pid},
        )
        coparties = [(str(x["pred"]), str(x["et"])) for x in coparty_raw]
        pid_coparties[pid] = coparties
        for other, _role in coparties:
            if other != anchor and other in related_lines:
                others_needed.add(other)
    attrs_others = _fetch_nodes_bulk(list(others_needed))
    for pid, anchor_pairs in policy_roles.items():
        coparties = pid_coparties[pid]
        dpol = _node_row_from_store(pid, attrs_pol[pid])
        pprops = dpol["parsed_props"]
        for other, other_role in coparties:
            if other == anchor:
                continue
            if other not in related_lines:
                continue
            key = (pid, other, "|".join(sorted(related_lines[other])))
            if key in seen:
                continue
            seen.add(key)
            olab = attrs_others.get(other, {}).get("label", other)
            for anchor_role in {r for p, r in anchor_pairs if p == anchor}:
                out_rows.append(
                    {
                        "policy_node_id": pid,
                        "POLICY_NUMBER": pprops.get("POLICY_NUMBER"),
                        "policy_label": dpol.get("label"),
                        "anchor_relationship_to_policy": anchor_role,
                        "related_person_node_id": other,
                        "related_person_label": olab,
                        "related_person_role_on_policy": other_role,
                        "person_person_ties": " ; ".join(related_lines[other]),
                    }
                )
    df = pd.DataFrame(out_rows)
    if df.empty:
        explanation_plain = (
            f"**{plab}** (`{anchor}`) has **no** policy in this extract where another party "
            "on the **same** policy also has a **direct** spouse/family/POA-style person→person "
            "link with them. (They may still share policies with unrelated parties.)"
        )
    else:
        explanation_plain = (
            f"Found **{len(df)}** policy–side pairing(s): **{plab}** shares a policy with "
            "someone they are **directly** tied to via a person→person relationship "
            "(same edge types as family/social clusters)."
        )
    evidence = [
        (
            f"{r['policy_node_id']}: anchor {anchor} ({r['anchor_relationship_to_policy']}); "
            f"related {r['related_person_node_id']} ({r['related_person_role_on_policy']}); "
            f"ties: {r['person_person_ties']}"
        )
        for r in out_rows
    ]
    summary = f"Person {anchor}: {len(df)} policy row(s) where a related person co-appears on the policy."
    return {
        "summary": summary,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence,
        "person_node_id": anchor,
        "table": df,
    }
