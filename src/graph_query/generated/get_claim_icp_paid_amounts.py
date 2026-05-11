"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
    from src.graph_query.native_read_mode import neo4j_native_reads_enabled

    if neo4j_native_reads_enabled():
        from src.graph_query.neo4j_native_extensions import run_extension_native

        return run_extension_native("get_claim_icp_paid_amounts", tool_input)

    G = get_graph()

    if claim_id not in G:
        return json.dumps({"error": f"Claim node '{claim_id}' not found in graph."})

    # Step 1: Find ICP nodes linked to the claim (successors and predecessors)
    icp_ids = []
    for neighbor in list(G.successors(claim_id)) + list(G.predecessors(claim_id)):
        node_data = G.nodes[neighbor]
        node_type = str(node_data.get("node_type", "")).lower()
        node_label = str(node_data.get("label", neighbor)).lower()
        if any(kw in node_type or kw in node_label for kw in ["icp", "independentcareprovider", "independent_care_provider", "independent care provider"]):
            if neighbor not in icp_ids:
                icp_ids.append(neighbor)

    if not icp_ids:
        return json.dumps({"claim_id": claim_id, "result": [], "note": "No ICP nodes found linked to this claim."})

    # Helper: extract a numeric amount from a node's properties
    amount_keys = ["paid_amount", "amount_paid", "paid", "amount", "payment_amount", "total_amount"]
    def extract_amount(node_data):
        for key in amount_keys:
            for prop_key, prop_val in node_data.items():
                if key in prop_key.lower():
                    try:
                        return float(prop_val)
                    except (TypeError, ValueError):
                        pass
        return None

    results = []

    for icp_id in icp_ids:
        icp_data = G.nodes[icp_id]
        icp_label = icp_data.get("label", icp_id)

        # Step 2: Find Payment nodes linked to this ICP (successors and predecessors)
        total_paid = 0.0
        payment_count = 0
        visited = set()

        for neighbor in list(G.successors(icp_id)) + list(G.predecessors(icp_id)):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            node_data = G.nodes[neighbor]
            node_type = str(node_data.get("node_type", "")).lower()
            node_label_n = str(node_data.get("label", neighbor)).lower()
            if "payment" in node_type or "payment" in node_label_n:
                amount = extract_amount(node_data)
                if amount is not None:
                    total_paid += amount
                    payment_count += 1

        results.append({
            "icp_id": icp_id,
            "icp_label": icp_label,
            "total_paid_amount": round(total_paid, 2),
            "payment_count": payment_count
        })

    results.sort(key=lambda x: x["total_paid_amount"], reverse=True)
    return json.dumps({"claim_id": claim_id, "icp_paid_amounts": results})
