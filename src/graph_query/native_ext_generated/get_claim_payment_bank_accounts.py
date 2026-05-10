"""get_claim_payment_bank_accounts: Traverses Claim → Payment → BankAccount in Neo4j."""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json


def run_native(tool_input: dict[str, Any]) -> str:
    """Return all bank accounts linked to payments on a given claim."""
    claim_id = tool_input.get("claim_id", "").strip()
    if not claim_id:
        return json.dumps({"error": "claim_id is required", "bank_accounts": []})

    # ------------------------------------------------------------------
    # Step 1: Resolve the Claim node – exact match on node_id first,
    #         then by label substring, then by any property substring.
    # ------------------------------------------------------------------
    resolve_query = """
    // Exact match on node_id
    MATCH (c:Entity)
    WHERE c.node_id = $claim_id
      AND (toLower(c.node_type) CONTAINS 'claim'
           OR c.label CONTAINS 'CLM'
           OR toLower(c.label) CONTAINS 'claim')
    RETURN c.node_id   AS node_id,
           c.label     AS label,
           c.node_type AS node_type,
           c.properties_json AS properties_json,
           1           AS priority

    UNION

    // Label substring match
    MATCH (c:Entity)
    WHERE c.label CONTAINS $claim_id
      AND (toLower(c.node_type) CONTAINS 'claim'
           OR c.label CONTAINS 'CLM'
           OR toLower(c.label) CONTAINS 'claim')
    RETURN c.node_id   AS node_id,
           c.label     AS label,
           c.node_type AS node_type,
           c.properties_json AS properties_json,
           2           AS priority

    UNION

    // Broad substring match across node_id / label / properties_json
    MATCH (c:Entity)
    WHERE (c.node_id CONTAINS $claim_id
           OR c.label CONTAINS $claim_id
           OR c.properties_json CONTAINS $claim_id)
    RETURN c.node_id   AS node_id,
           c.label     AS label,
           c.node_type AS node_type,
           c.properties_json AS properties_json,
           3           AS priority

    ORDER BY priority ASC
    LIMIT 1
    """

    claim_rows = rq(resolve_query, {"claim_id": claim_id})
    if not claim_rows:
        return json.dumps({
            "error": f"Claim node not found for id: {claim_id}",
            "bank_accounts": []
        })

    claim_row = claim_rows[0]
    claim_node_id = claim_row["node_id"]
    claim_label = claim_row["label"] or claim_node_id

    # ------------------------------------------------------------------
    # Step 2 + 3: In a single Cypher statement traverse
    #   Claim --(any direction)--> Payment --(any direction)--> BankAccount
    # We accept edges in either direction between the three node types.
    # ------------------------------------------------------------------
    traverse_query = """
    // Find the resolved claim node
    MATCH (c:Entity {node_id: $claim_node_id})

    // Payment nodes reachable from the claim in either direction
    MATCH (c)-[r1:GRAPH_EDGE]-(p:Entity)
    WHERE toLower(p.node_type) CONTAINS 'payment'
       OR toLower(p.label)     CONTAINS 'payment'

    // BankAccount nodes reachable from each payment in either direction
    MATCH (p)-[r2:GRAPH_EDGE]-(b:Entity)
    WHERE toLower(b.node_type) CONTAINS 'bank'
       OR toLower(b.label)     CONTAINS 'bank'
       OR toLower(b.node_type) CONTAINS 'account'

    RETURN
        p.node_id          AS payment_id,
        p.label            AS payment_label,
        p.node_type        AS payment_type,
        p.properties_json  AS payment_props,
        b.node_id          AS ba_id,
        b.label            AS ba_label,
        b.node_type        AS ba_type,
        b.properties_json  AS ba_props

    ORDER BY payment_id, ba_id
    LIMIT 500
    """

    rows = rq(traverse_query, {"claim_node_id": claim_node_id})

    if not rows:
        # Check if at least some payment nodes exist (no bank accounts found)
        payment_check_query = """
        MATCH (c:Entity {node_id: $claim_node_id})-[r:GRAPH_EDGE]-(p:Entity)
        WHERE toLower(p.node_type) CONTAINS 'payment'
           OR toLower(p.label)     CONTAINS 'payment'
        RETURN p.node_id AS payment_id, p.label AS payment_label, p.node_type AS payment_type
        LIMIT 100
        """
        payment_rows = rq(payment_check_query, {"claim_node_id": claim_node_id})

        if not payment_rows:
            return json.dumps({
                "claim_id": claim_node_id,
                "claim_label": claim_label,
                "payment_count": 0,
                "payment_nodes": [],
                "bank_accounts": [],
                "bank_account_count": 0,
                "message": "No Payment nodes found linked to this claim."
            })

        # Payments exist but no bank accounts
        payments_out = []
        for pr in payment_rows:
            props = parse_properties_json(pr.get("payment_props") or "{}")
            payments_out.append({
                "payment_id": pr["payment_id"],
                "label": pr["payment_label"] or pr["payment_id"],
                "node_type": pr["payment_type"] or "unknown",
                "bank_accounts": [],
                **{k: v for k, v in props.items()}
            })

        return json.dumps({
            "claim_id": claim_node_id,
            "claim_label": claim_label,
            "payment_count": len(payments_out),
            "payments": payments_out,
            "bank_account_count": 0,
            "bank_accounts": [],
            "message": "Payment nodes found but no BankAccount nodes are linked to them."
        })

    # ------------------------------------------------------------------
    # Build structured output
    # ------------------------------------------------------------------
    # payment_id -> {meta + ba_list}
    payments: dict[str, dict[str, Any]] = {}
    # ba_id -> ba_entry (deduplicated)
    bank_accounts: dict[str, dict[str, Any]] = {}

    for row in rows:
        pid = row["payment_id"]
        if pid not in payments:
            p_props = parse_properties_json(row.get("payment_props") or "{}")
            payments[pid] = {
                "payment_id": pid,
                "label": row["payment_label"] or pid,
                "node_type": row["payment_type"] or "unknown",
                "bank_accounts": [],
                **{k: v for k, v in p_props.items()}
            }

        ba_id = row["ba_id"]
        if ba_id is None:
            continue

        if ba_id not in bank_accounts:
            b_props = parse_properties_json(row.get("ba_props") or "{}")
            ba_entry: dict[str, Any] = {
                "bank_account_id": ba_id,
                "label": row["ba_label"] or ba_id,
                "node_type": row["ba_type"] or "unknown",
                **{k: v for k, v in b_props.items()}
            }
            bank_accounts[ba_id] = ba_entry

        # Attach to payment (avoid duplicates)
        payment_ba_ids = {ba["bank_account_id"] for ba in payments[pid]["bank_accounts"]}
        if ba_id not in payment_ba_ids:
            payments[pid]["bank_accounts"].append(bank_accounts[ba_id])

    return json.dumps({
        "claim_id": claim_node_id,
        "claim_label": claim_label,
        "payment_count": len(payments),
        "payments": list(payments.values()),
        "bank_account_count": len(bank_accounts),
        "bank_accounts": list(bank_accounts.values())
    }, default=str)