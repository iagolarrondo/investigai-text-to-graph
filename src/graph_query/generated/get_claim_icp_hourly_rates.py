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

        return run_extension_native("get_claim_icp_hourly_rates", tool_input)

    G = get_graph()

    if claim_id not in G:
        return json.dumps({"error": f"Claim node '{claim_id}' not found in graph.", "icps": []})

    rate_keywords = ("hourly_rate", "rate", "compensation")
    icp_keywords = ("icp", "independentcare", "independent_care", "independent care")

    def is_icp_node(node_id: str) -> bool:
        data = G.nodes[node_id]
        node_type = str(data.get("node_type", "")).lower().replace(" ", "")
        label = str(data.get("label", node_id)).lower().replace(" ", "")
        for kw in icp_keywords:
            kw_clean = kw.replace(" ", "")
            if kw_clean in node_type or kw_clean in label:
                return True
        return False

    def extract_rate_props(node_id: str) -> dict:
        data = G.nodes[node_id]
        found = {}
        for k, v in data.items():
            k_lower = k.lower()
            if any(kw in k_lower for kw in rate_keywords):
                found[k] = v
        return found

    # Collect all neighbors (successors + predecessors) of the claim node
    neighbors = set()
    if hasattr(G, 'successors'):
        neighbors.update(G.successors(claim_id))
    if hasattr(G, 'predecessors'):
        neighbors.update(G.predecessors(claim_id))

    # Also do a 2-hop search in case ICPs are one hop away from an intermediary
    two_hop = set()
    for n in neighbors:
        if hasattr(G, 'successors'):
            two_hop.update(G.successors(n))
        if hasattr(G, 'predecessors'):
            two_hop.update(G.predecessors(n))
    two_hop.discard(claim_id)
    all_candidates = neighbors | two_hop

    results = []
    seen = set()
    for node_id in all_candidates:
        if node_id in seen:
            continue
        if not is_icp_node(node_id):
            continue
        seen.add(node_id)
        data = G.nodes[node_id]
        rate_props = extract_rate_props(node_id)
        # Determine hop distance
        hop = 1 if node_id in neighbors else 2
        results.append({
            "icp_id": node_id,
            "icp_label": data.get("label", node_id),
            "node_type": data.get("node_type", ""),
            "hop_from_claim": hop,
            "rate_properties": rate_props if rate_props else None
        })

    # Sort: 1-hop first, then alphabetically by icp_id
    results.sort(key=lambda x: (x["hop_from_claim"], x["icp_id"]))

    if not results:
        # Fallback: list all neighbor node types to help diagnose
        neighbor_types = {}
        for n in neighbors:
            nt = G.nodes[n].get("node_type", "unknown")
            neighbor_types[nt] = neighbor_types.get(nt, 0) + 1
        return json.dumps({
            "claim_id": claim_id,
            "icps_found": 0,
            "message": "No ICP nodes found within 2 hops of this claim.",
            "neighbor_node_types_1hop": neighbor_types
        })

    return json.dumps({
        "claim_id": claim_id,
        "icps_found": len(results),
        "icps": results
    })
