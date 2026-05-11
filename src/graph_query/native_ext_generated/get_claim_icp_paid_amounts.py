"""get_claim_icp_paid_amounts: Traverses Claim → ICP nodes, then ICP → Payment nodes,
and returns total paid amount per ICP for a given claim.
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json

# Keys we scan (in priority order) when looking for a monetary amount
_AMOUNT_KEYS = ["paid_amount", "amount_paid", "paid", "amount", "payment_amount", "total_amount"]


def _extract_amount(props: dict) -> float | None:
    """Return the first numeric value whose key contains an amount-related keyword."""
    for key in _AMOUNT_KEYS:
        for prop_key, prop_val in props.items():
            if key in prop_key.lower():
                try:
                    return float(prop_val)
                except (TypeError, ValueError):
                    pass
    return None


def run_native(tool_input: dict[str, Any]) -> str:
    claim_id: str = tool_input.get("claim_id", "").strip()
    if not claim_id:
        return json.dumps({"error": "claim_id is required."})

    # ------------------------------------------------------------------
    # Step 0: Verify the claim node exists
    # ------------------------------------------------------------------
    existence_rows = rq(
        """
        MATCH (c:Entity {node_id: $claim_id})
        RETURN c.node_id AS node_id
        LIMIT 1
        """,
        {"claim_id": claim_id},
    )
    if not existence_rows:
        return json.dumps({"error": f"Claim node '{claim_id}' not found in graph."})

    # ------------------------------------------------------------------
    # Step 1: Find ICP nodes linked to the claim (in either direction)
    # ICP nodes are identified by node_type or label containing
    # 'icp', 'independentcareprovider', or 'independent'
    # ------------------------------------------------------------------
    icp_rows = rq(
        """
        MATCH (c:Entity {node_id: $claim_id})-[r:GRAPH_EDGE]-(icp:Entity)
        WHERE toLower(icp.node_type) CONTAINS 'icp'
           OR toLower(icp.node_type) CONTAINS 'independentcareprovider'
           OR toLower(icp.node_type) CONTAINS 'independent'
           OR toLower(icp.label)     CONTAINS 'icp'
           OR toLower(icp.label)     CONTAINS 'independentcareprovider'
           OR toLower(icp.label)     CONTAINS 'independent care provider'
        RETURN DISTINCT
            icp.node_id          AS icp_id,
            icp.label            AS icp_label,
            icp.properties_json  AS icp_props_json
        LIMIT 200
        """,
        {"claim_id": claim_id},
    )

    if not icp_rows:
        return json.dumps({
            "claim_id": claim_id,
            "result": [],
            "note": "No ICP nodes found linked to this claim.",
        })

    # ------------------------------------------------------------------
    # Step 2: For each ICP, find Payment nodes linked to it (either
    # direction) and sum numeric amount-like properties.
    # We do this in a single batched Cypher query.
    # ------------------------------------------------------------------
    icp_ids = [row["icp_id"] for row in icp_rows]

    payment_rows = rq(
        """
        MATCH (icp:Entity)-[r:GRAPH_EDGE]-(pmt:Entity)
        WHERE icp.node_id IN $icp_ids
          AND (
                toLower(pmt.node_type) CONTAINS 'payment'
             OR toLower(pmt.label)     CONTAINS 'payment'
          )
        RETURN
            icp.node_id         AS icp_id,
            pmt.node_id         AS pmt_id,
            pmt.properties_json AS pmt_props_json
        LIMIT 2000
        """,
        {"icp_ids": icp_ids},
    )

    # ------------------------------------------------------------------
    # Step 3: Aggregate totals per ICP in Python
    # ------------------------------------------------------------------
    # Build a lookup from icp_id → (label, total_paid, payment_count)
    icp_meta: dict[str, dict] = {}
    for row in icp_rows:
        icp_meta[row["icp_id"]] = {
            "icp_label": row["icp_label"] or row["icp_id"],
            "total_paid_amount": 0.0,
            "payment_count": 0,
            "_seen_pmts": set(),
        }

    for row in payment_rows:
        icp_id = row["icp_id"]
        pmt_id = row["pmt_id"]
        if icp_id not in icp_meta:
            continue
        bucket = icp_meta[icp_id]
        # Deduplicate: a payment node may appear via both in- and out-edges
        if pmt_id in bucket["_seen_pmts"]:
            continue
        bucket["_seen_pmts"].add(pmt_id)

        # Parse the payment properties and extract a numeric amount
        try:
            props = parse_properties_json(row.get("pmt_props_json") or "{}")
        except Exception:
            try:
                props = json.loads(row.get("pmt_props_json") or "{}")
            except Exception:
                props = {}

        amount = _extract_amount(props)
        if amount is not None:
            bucket["total_paid_amount"] += amount
            bucket["payment_count"] += 1

    # ------------------------------------------------------------------
    # Step 4: Build and return the result list, sorted descending by total
    # ------------------------------------------------------------------
    results = [
        {
            "icp_id": icp_id,
            "icp_label": meta["icp_label"],
            "total_paid_amount": round(meta["total_paid_amount"], 2),
            "payment_count": meta["payment_count"],
        }
        for icp_id, meta in icp_meta.items()
    ]
    results.sort(key=lambda x: x["total_paid_amount"], reverse=True)

    return json.dumps({"claim_id": claim_id, "icp_paid_amounts": results})