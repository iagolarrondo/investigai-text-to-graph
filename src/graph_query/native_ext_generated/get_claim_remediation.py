"""get_claim_remediation – Neo4j/Cypher native implementation.

Given a claim_id, traverses the graph (up to 3 hops, both directions) from the
Claim node to any Remediation-, Recovery-, or Resolution-type nodes and returns
their properties (status, recovery_amount, date, type, etc.).
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json

# ---------------------------------------------------------------------------
# Keywords that mark a node or edge as remediation-related
# ---------------------------------------------------------------------------
_REMEDIATION_KEYWORDS = [
    "remediation", "recovery", "resolution", "restitution",
    "repayment", "refund", "settlement",
]

# Pre-built regex fragment used inside Cypher (case-insensitive WHERE clause)
_KW_PATTERN = "|".join(_REMEDIATION_KEYWORDS)   # used in Python filter only


def _matches_remediation(text: str) -> bool:
    """Return True when *text* contains any remediation keyword."""
    t = text.lower()
    return any(kw in t for kw in _REMEDIATION_KEYWORDS)


def _extract_key_fields(props: dict) -> dict:
    """Return a sub-dict of props whose keys contain financially relevant terms."""
    target_terms = {
        "amount", "status", "date", "recovery", "type", "note",
        "result", "resolut", "refund", "payment", "remediat",
    }
    return {
        k: v for k, v in props.items()
        if any(t in k.lower() for t in target_terms)
    }


def _parse_node(raw: dict) -> dict:
    """Merge top-level node fields with parsed properties_json."""
    node = dict(raw)
    extra = parse_properties_json(node.pop("properties_json", None) or "{}")
    node.update(extra)
    return node


def run_native(tool_input: dict[str, Any]) -> str:
    """Entry point – returns a JSON string."""
    claim_id = tool_input.get("claim_id", "").strip()
    if not claim_id:
        return json.dumps({"error": "claim_id is required"})

    # ------------------------------------------------------------------
    # 1. Fetch the claim node itself
    # ------------------------------------------------------------------
    claim_rows = rq(
        """
        MATCH (c:Entity {node_id: $claim_id})
        RETURN c.node_id        AS node_id,
               c.node_type      AS node_type,
               c.label          AS label,
               c.source_table   AS source_table,
               c.properties_json AS properties_json
        LIMIT 1
        """,
        {"claim_id": claim_id},
    )

    if not claim_rows:
        return json.dumps({
            "error": f"Node '{claim_id}' not found in graph",
            "claim_id": claim_id,
        })

    claim_props = _parse_node(dict(claim_rows[0]))

    # Extract any recovery-related properties sitting directly on the claim node
    recovery_prop_terms = {
        "recovery", "remediat", "resolut", "refund", "settlement",
        "restitut", "repay",
    }
    claim_level_recovery = {
        k: v for k, v in claim_props.items()
        if any(t in k.lower() for t in recovery_prop_terms)
    }

    # ------------------------------------------------------------------
    # 2. BFS up to 3 hops (outgoing + incoming), collect ALL neighbour
    #    nodes + edges so we can filter in Python for remediation markers.
    #    We pull at most 500 paths to keep result sets bounded.
    # ------------------------------------------------------------------
    traversal_rows = rq(
        """
        MATCH path = (start:Entity {node_id: $claim_id})
                     -[r:GRAPH_EDGE*1..3]-
                     (other:Entity)
        WHERE other.node_id <> $claim_id
        WITH other,
             relationships(path)        AS rels,
             length(path)               AS hop,
             [rel IN relationships(path) | type(rel)] AS edge_types_list
        RETURN DISTINCT
               other.node_id           AS node_id,
               other.node_type         AS node_type,
               other.label             AS label,
               other.source_table      AS source_table,
               other.properties_json   AS properties_json,
               hop,
               // last edge on the path (closest to `other`)
               rels[-1].edge_type       AS last_edge_type,
               rels[-1].edge_id         AS last_edge_id,
               rels[-1].properties_json AS last_edge_props_json
        ORDER BY hop ASC
        LIMIT 500
        """,
        {"claim_id": claim_id},
    )

    # ------------------------------------------------------------------
    # 3. Filter traversal results for remediation-relevant nodes / edges
    # ------------------------------------------------------------------
    found_nodes: list[dict] = []
    seen_node_ids: set[str] = {claim_id}

    for raw in traversal_rows:
        row = dict(raw)
        nid = row.get("node_id") or ""
        if nid in seen_node_ids:
            continue

        node_type = row.get("node_type") or ""
        label = row.get("label") or ""
        edge_type = row.get("last_edge_type") or ""

        is_rem_node = _matches_remediation(node_type) or _matches_remediation(label)
        is_rem_edge = _matches_remediation(edge_type)

        if not (is_rem_node or is_rem_edge):
            # Also check properties_json text for keywords as a fallback
            raw_pj = row.get("properties_json") or ""
            if not _matches_remediation(raw_pj):
                continue

        seen_node_ids.add(nid)

        node_merged = _parse_node({
            "node_id":        nid,
            "node_type":      node_type,
            "label":          label,
            "source_table":   row.get("source_table"),
            "properties_json": row.get("properties_json"),
        })

        # Parse edge properties too
        edge_extra = parse_properties_json(row.get("last_edge_props_json") or "{}")

        entry: dict[str, Any] = {
            "node_id":          nid,
            "node_type":        node_type,
            "label":            label,
            "reached_via_edge": edge_type,
            "hop":              row.get("hop"),
        }
        # Merge key financial/status fields from node
        entry.update(_extract_key_fields(node_merged))
        # Merge key fields from the connecting edge
        edge_key = _extract_key_fields(edge_extra)
        for k, v in edge_key.items():
            if k not in entry:
                entry[f"edge_{k}"] = v

        found_nodes.append(entry)

    # ------------------------------------------------------------------
    # 4. Build final result
    # ------------------------------------------------------------------
    result: dict[str, Any] = {
        "claim_id":                       claim_id,
        "claim_properties":               claim_props,
        "claim_level_recovery_properties": claim_level_recovery,
        "remediation_nodes_found":        len(found_nodes),
        "remediations":                   found_nodes,
    }

    if not found_nodes and not claim_level_recovery:
        result["note"] = (
            "No remediation, recovery, or resolution nodes found within 3 hops "
            "of this claim, and no recovery-related properties on the claim node itself."
        )

    return json.dumps(result, default=str)