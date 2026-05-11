"""get_claim_icp_hourly_rates – Neo4j/Cypher native implementation.

Traverses from a Claim node (up to 2 hops) to any ICP
(Independent Care Provider / IndependentCareProvider) nodes and returns
each ICP's node id, label, node_type, hop distance, and any properties
whose key contains 'hourly_rate', 'rate', or 'compensation'.
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_ICP_KEYWORDS = ("icp", "independentcare", "independent_care", "independentcareprovider")
_RATE_KEYWORDS = ("hourly_rate", "rate", "compensation")


def _is_icp_node(node_type: str, label: str) -> bool:
    nt = node_type.lower().replace(" ", "").replace("_", "")
    lb = label.lower().replace(" ", "").replace("_", "")
    for kw in _ICP_KEYWORDS:
        kw_clean = kw.replace("_", "")
        if kw_clean in nt or kw_clean in lb:
            return True
    return False


def _extract_rate_props(props: dict) -> dict:
    found: dict[str, Any] = {}
    for k, v in props.items():
        if any(kw in k.lower() for kw in _RATE_KEYWORDS):
            found[k] = v
    return found


# ---------------------------------------------------------------------------
# main entry-point
# ---------------------------------------------------------------------------

def run_native(tool_input: dict[str, Any]) -> str:
    claim_id: str = tool_input.get("claim_id", "").strip()
    if not claim_id:
        return json.dumps({"error": "claim_id is required.", "icps": []})

    # ------------------------------------------------------------------
    # 1. Verify the claim node exists
    # ------------------------------------------------------------------
    exist_rows = rq(
        "MATCH (c:Entity {node_id: $cid}) RETURN c.node_id AS node_id LIMIT 1",
        {"cid": claim_id},
    )
    if not exist_rows:
        return json.dumps(
            {"error": f"Claim node '{claim_id}' not found in graph.", "icps": []}
        )

    # ------------------------------------------------------------------
    # 2. Fetch 1-hop neighbours (both directions)
    # ------------------------------------------------------------------
    one_hop_rows = rq(
        """
        MATCH (c:Entity {node_id: $cid})-[*1]-(n:Entity)
        RETURN DISTINCT
            n.node_id       AS node_id,
            n.node_type     AS node_type,
            n.label         AS label,
            n.properties_json AS properties_json,
            1               AS hop
        LIMIT 500
        """,
        {"cid": claim_id},
    )

    one_hop_ids: set[str] = {r["node_id"] for r in one_hop_rows if r["node_id"]}

    # ------------------------------------------------------------------
    # 3. Fetch 2-hop neighbours (both directions), excluding claim itself
    # ------------------------------------------------------------------
    two_hop_rows = rq(
        """
        MATCH (c:Entity {node_id: $cid})-[*2]-(n:Entity)
        WHERE n.node_id <> $cid
        RETURN DISTINCT
            n.node_id       AS node_id,
            n.node_type     AS node_type,
            n.label         AS label,
            n.properties_json AS properties_json,
            2               AS hop
        LIMIT 1000
        """,
        {"cid": claim_id},
    )

    # ------------------------------------------------------------------
    # 4. Merge rows – keep lowest hop per node_id
    # ------------------------------------------------------------------
    merged: dict[str, dict] = {}
    for row in one_hop_rows + two_hop_rows:
        nid = row.get("node_id")
        if not nid:
            continue
        hop = int(row.get("hop", 2))
        if nid not in merged or hop < merged[nid]["hop"]:
            merged[nid] = {
                "node_id": nid,
                "node_type": row.get("node_type") or "",
                "label": row.get("label") or nid,
                "properties_json": row.get("properties_json") or "{}",
                "hop": hop,
            }

    # ------------------------------------------------------------------
    # 5. Filter to ICP nodes and extract rate properties
    # ------------------------------------------------------------------
    results: list[dict] = []
    seen: set[str] = set()

    for nid, data in merged.items():
        if nid in seen:
            continue
        node_type = data["node_type"]
        label = data["label"]
        if not _is_icp_node(node_type, label):
            continue
        seen.add(nid)

        # Parse the JSON property bag stored in properties_json
        try:
            props: dict = parse_properties_json(data["properties_json"])
        except Exception:
            try:
                props = json.loads(data["properties_json"])
            except Exception:
                props = {}

        rate_props = _extract_rate_props(props)

        results.append(
            {
                "icp_id": nid,
                "icp_label": label,
                "node_type": node_type,
                "hop_from_claim": data["hop"],
                "rate_properties": rate_props if rate_props else None,
            }
        )

    # Sort: 1-hop first, then alphabetically by icp_id
    results.sort(key=lambda x: (x["hop_from_claim"], x["icp_id"]))

    # ------------------------------------------------------------------
    # 6. Return results (or diagnostic fallback)
    # ------------------------------------------------------------------
    if not results:
        # Build neighbour-type histogram for diagnostics
        neighbor_types: dict[str, int] = {}
        for nid, data in merged.items():
            if data["hop"] == 1:
                nt = data["node_type"] or "unknown"
                neighbor_types[nt] = neighbor_types.get(nt, 0) + 1

        return json.dumps(
            {
                "claim_id": claim_id,
                "icps_found": 0,
                "message": "No ICP nodes found within 2 hops of this claim.",
                "neighbor_node_types_1hop": neighbor_types,
            }
        )

    return json.dumps(
        {
            "claim_id": claim_id,
            "icps_found": len(results),
            "icps": results,
        }
    )