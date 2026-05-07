"""
Neo4j **native reads** for investigation tools — same return shapes as ``query_graph``.

Natural language → LLM picks **tools** (unchanged) → Python wrappers here run **Cypher** against
``:Entity`` / ``:GRAPH_EDGE`` (see ``sync_processed``). No full-graph hydrate.

Internal helpers :func:`list_node_ids_by_type` / :func:`list_edge_rows_by_type` also use Cypher when
native reads are on. Extension tools delegate from ``generated/*.py`` to
:mod:`src.graph_query.neo4j_native_extensions` for the same Aura model.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from src.graph_store.neo4j_read_session import run_read_query, run_read_transaction

__all__ = [
    "summarize_graph",
    "get_graph_relationship_catalog",
    "search_nodes",
    "get_neighbors",
    "get_person_policies",
    "claim_node_id_first_match",
    "list_node_ids_by_type",
    "list_edge_rows_by_type",
]


def parse_properties_json(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}


def summarize_graph() -> dict:
    def work(tx):
        num_nodes = tx.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
        num_edges = tx.run("MATCH ()-[r:GRAPH_EDGE]->() RETURN count(r) AS c").single()["c"]
        node_types: dict[str, int] = {}
        for r in tx.run(
            "MATCH (n:Entity) RETURN coalesce(n.node_type, '(missing)') AS nt, count(*) AS c"
        ):
            node_types[str(r["nt"])] = int(r["c"])
        edge_types: dict[str, int] = {}
        for r in tx.run(
            "MATCH ()-[r:GRAPH_EDGE]->() RETURN coalesce(r.edge_type, '(missing)') AS et, count(*) AS c"
        ):
            edge_types[str(r["et"])] = int(r["c"])
        return {
            "num_nodes": int(num_nodes),
            "num_edges": int(num_edges),
            "node_types": dict(sorted(node_types.items())),
            "edge_types": dict(sorted(edge_types.items())),
            "is_directed": True,
        }

    return run_read_transaction(work)


def get_graph_relationship_catalog() -> dict[str, Any]:
    rows_raw = run_read_query(
        """
        MATCH (a:Entity)-[r:GRAPH_EDGE]->(b:Entity)
        RETURN coalesce(a.node_type, '(missing)') AS from_node_type,
               coalesce(r.edge_type, '(missing)') AS edge_type,
               coalesce(b.node_type, '(missing)') AS to_node_type,
               count(*) AS count
        ORDER BY count DESC
        """
    )
    rows = [
        {
            "from_node_type": str(r["from_node_type"]),
            "edge_type": str(r["edge_type"]),
            "to_node_type": str(r["to_node_type"]),
            "count": int(r["count"]),
        }
        for r in rows_raw
    ]
    df = pd.DataFrame(rows)
    explanation_plain = (
        "Each row is a **directed pattern** stored in this extract: entities of type "
        "**from_node_type** connect to **to_node_type** via **edge_type** (arrow follows the CSV). "
        "Multi-hop questions can be planned by chaining these shapes. Counts help you judge "
        "how common a path is in the demo book."
    )
    summary = (
        f"{len(rows)} distinct relationship shape(s); reading counts from Neo4j."
    )
    return {
        "summary": summary,
        "explanation_plain": explanation_plain,
        "evidence_bullets": [],
        "table": df,
    }


def search_nodes(
    query: str,
    *,
    node_type: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"summary": "Empty query.", "matches": pd.DataFrame()}
    qlower = q.lower()
    lim = max(1, min(limit, 200))
    nt = (node_type or "").strip() or None
    rows = run_read_query(
        """
        MATCH (n:Entity)
        WHERE ($node_type IS NULL OR n.node_type = $node_type)
          AND (
            toLower(toString(n.label)) CONTAINS $qlower
            OR toLower(toString(n.properties_json)) CONTAINS $qlower
          )
        RETURN n.node_id AS node_id,
               n.node_type AS node_type,
               n.label AS label,
               CASE
                 WHEN toLower(toString(n.label)) CONTAINS $qlower THEN 'label'
                 ELSE 'properties'
               END AS match_reason
        ORDER BY n.node_type, n.node_id
        LIMIT $limit
        """,
        {"qlower": qlower, "node_type": nt, "limit": lim},
    )
    df = pd.DataFrame([dict(r) for r in rows])
    summary = f"search_nodes({q!r}" + (f", node_type={node_type!r}" if node_type else "") + f"): {len(df)} match(es)."
    return {"summary": summary, "matches": df, "query": q, "node_type_filter": node_type}


def get_neighbors(node_id: str) -> dict[str, list[str]]:
    nid = (node_id or "").strip()
    # Single round-trip: existence check + both directions via pattern comprehensions.
    rows = run_read_query(
        """
        MATCH (n:Entity {node_id: $id})
        RETURN
          [(n)-[:GRAPH_EDGE]->(out:Entity) | out.node_id] AS outgoing,
          [(inc:Entity)-[:GRAPH_EDGE]->(n) | inc.node_id] AS incoming
        """,
        {"id": nid},
    )
    if not rows:
        raise KeyError(f"Unknown node_id: {nid!r}")
    outgoing = sorted(str(x) for x in (rows[0]["outgoing"] or []))
    incoming = sorted(str(x) for x in (rows[0]["incoming"] or []))
    return {"outgoing": outgoing, "incoming": incoming}


def get_person_policies(person_node_id: str) -> dict[str, Any]:
    pid = (person_node_id or "").strip()
    # Single round-trip: person metadata + all linked policies via pattern comprehension.
    anchor = run_read_query(
        """
        MATCH (p:Entity {node_id: $pid})
        RETURN p.node_type AS nt, p.label AS lab,
          [(p)-[r:GRAPH_EDGE]->(pol:Entity)
           WHERE pol.node_type = 'Policy'
             AND r.edge_type IN ['IS_COVERED_BY', 'SOLD_POLICY']
           | {rel: r.edge_type, pid: pol.node_id, lab: pol.label, pj: pol.properties_json}
          ] AS policies
        """,
        {"pid": pid},
    )
    if not anchor:
        raise KeyError(f"Unknown node_id: {pid!r}")
    if str(anchor[0].get("nt") or "") != "Person":
        raise ValueError(f"Node {pid!r} is not a Person node")
    plab = anchor[0].get("lab") or pid

    rows: list[dict[str, Any]] = []
    for pol in (anchor[0]["policies"] or []):
        props = parse_properties_json(pol.get("pj"))
        rows.append(
            {
                "person_node_id": pid,
                "relationship_to_policy": str(pol["rel"]),
                "policy_node_id": str(pol["pid"]),
                "policy_label": pol.get("lab"),
                "POLICY_NUMBER": props.get("POLICY_NUMBER"),
                "POLICY_STATUS": props.get("POLICY_STATUS"),
            }
        )
    df = pd.DataFrame(rows)
    plab = plab
    if df.empty:
        explanation_plain = (
            f"No **Policy** nodes are linked from **{plab}** (`{pid}`) with "
            "**IS_COVERED_BY** or **SOLD_POLICY** in this extract."
        )
    else:
        explanation_plain = (
            f"Person **{plab}** (`{pid}`) has **{len(df)}** policy link(s) "
            "in the graph (insured and/or writing-agent roles)."
        )
    evidence: list[str] = []
    for _, r in df.iterrows():
        evidence.append(
            f"{r['person_node_id']} —[{r['relationship_to_policy']}]→ {r['policy_node_id']}"
        )
    summary = f"Person {pid}: {len(df)} policy link(s)."
    return {
        "summary": summary,
        "explanation_plain": explanation_plain,
        "evidence_bullets": evidence,
        "person_node_id": pid,
        "policies": df,
    }


def list_node_ids_by_type(node_type: str) -> list[str]:
    """All ``node_id`` values with the given ``node_type`` (Neo4j native)."""
    nt = (node_type or "").strip()
    if not nt:
        return []
    rows = run_read_query(
        """
        MATCH (n:Entity {node_type: $nt})
        RETURN n.node_id AS id
        ORDER BY id
        """,
        {"nt": nt},
    )
    return [str(r["id"]) for r in rows]


def list_edge_rows_by_type(edge_type: str) -> list[dict[str, Any]]:
    """Edges with ``edge_type``, same key shape as the NetworkX path in ``query_graph``."""
    et = (edge_type or "").strip()
    if not et:
        return []
    rows = run_read_query(
        """
        MATCH (a:Entity)-[r:GRAPH_EDGE]->(b:Entity)
        WHERE r.edge_type = $et
        RETURN a.node_id AS source,
               b.node_id AS target,
               r.edge_id AS edge_id,
               r.edge_type AS edge_type,
               r.source_table AS source_table,
               r.properties_json AS properties_json
        ORDER BY source, target, coalesce(r.edge_id, '')
        """,
        {"et": et},
    )
    return [
        {
            "source": str(r["source"]),
            "target": str(r["target"]),
            "edge_id": r.get("edge_id"),
            "edge_type": r.get("edge_type"),
            "source_table": r.get("source_table"),
            "properties_json": r.get("properties_json"),
        }
        for r in rows
    ]


def claim_node_id_first_match(candidates: list[str]) -> str | None:
    """First candidate (in order) that exists as a Claim node in Neo4j, or ``None``."""
    for cid in candidates:
        rows = run_read_query(
            """
            MATCH (c:Entity {node_id: $id})
            WHERE c.node_type = 'Claim'
            RETURN c.node_id AS id LIMIT 1
            """,
            {"id": cid},
        )
        if rows:
            return str(rows[0]["id"])
    return None
