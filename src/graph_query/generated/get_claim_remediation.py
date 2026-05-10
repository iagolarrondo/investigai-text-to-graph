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

        return run_extension_native("get_claim_remediation", tool_input)

    claim_id = tool_input.get("claim_id", "").strip()
    if not claim_id:
        return json.dumps({"error": "claim_id is required"})

    G = get_graph()

    if claim_id not in G:
        return json.dumps({"error": f"Node '{claim_id}' not found in graph", "claim_id": claim_id})

    node_data = G.nodes[claim_id]
    if node_data.get("node_type", "").lower() not in ("claim", ""):
        # still proceed, just note it
        pass

    # Keywords that suggest remediation / recovery / resolution nodes
    remediation_keywords = {"remediation", "recovery", "resolution", "restitution", "repayment", "refund", "settlement"}

    def _is_remediation_node(nid):
        ndata = G.nodes[nid]
        ntype = ndata.get("node_type", "").lower()
        label = ndata.get("label", "").lower()
        return any(kw in ntype or kw in label for kw in remediation_keywords)

    def _is_remediation_edge(etype):
        etype_l = etype.lower()
        return any(kw in etype_l for kw in remediation_keywords)

    found_nodes = []
    visited = set()

    # BFS up to 3 hops from the claim node, collecting remediation-related nodes
    from collections import deque
    queue = deque()
    queue.append((claim_id, 0))
    visited.add(claim_id)

    while queue:
        current, depth = queue.popleft()
        if depth >= 3:
            continue

        # Check outgoing edges
        for successor in G.successors(current):
            edge_data = G.edges[current, successor]
            edge_type = edge_data.get("edge_type", edge_data.get("relationship", ""))
            is_rem_edge = _is_remediation_edge(edge_type)
            is_rem_node = _is_remediation_node(successor)

            if is_rem_node or is_rem_edge:
                if successor not in visited:
                    visited.add(successor)
                    node_props = dict(G.nodes[successor])
                    found_nodes.append({
                        "node_id": successor,
                        "reached_via": edge_type,
                        "direction": "outgoing",
                        "hop": depth + 1,
                        "properties": node_props
                    })
                    queue.append((successor, depth + 1))
            elif successor not in visited:
                visited.add(successor)
                queue.append((successor, depth + 1))

        # Check incoming edges
        for predecessor in G.predecessors(current):
            edge_data = G.edges[predecessor, current]
            edge_type = edge_data.get("edge_type", edge_data.get("relationship", ""))
            is_rem_edge = _is_remediation_edge(edge_type)
            is_rem_node = _is_remediation_node(predecessor)

            if is_rem_node or is_rem_edge:
                if predecessor not in visited:
                    visited.add(predecessor)
                    node_props = dict(G.nodes[predecessor])
                    found_nodes.append({
                        "node_id": predecessor,
                        "reached_via": edge_type,
                        "direction": "incoming",
                        "hop": depth + 1,
                        "properties": node_props
                    })
                    queue.append((predecessor, depth + 1))
            elif predecessor not in visited:
                visited.add(predecessor)
                queue.append((predecessor, depth + 1))

    # Also scan claim node's own properties for recovery/remediation fields
    recovery_props = {}
    for k, v in node_data.items():
        k_lower = k.lower()
        if any(kw in k_lower for kw in {"recovery", "remediat", "resolut", "refund", "settlement", "restitut", "repay"}):
            recovery_props[k] = v

    # Extract key financial fields from found nodes
    summary_remediations = []
    for fn in found_nodes:
        props = fn["properties"]
        entry = {
            "node_id": fn["node_id"],
            "node_type": props.get("node_type", "unknown"),
            "label": props.get("label", ""),
            "reached_via_edge": fn["reached_via"],
            "hop": fn["hop"]
        }
        # Extract any amount / status / date fields
        for k, v in props.items():
            k_lower = k.lower()
            if any(kw in k_lower for kw in {"amount", "status", "date", "recovery", "type", "note", "result", "resolut", "refund", "payment"}):
                entry[k] = v
        summary_remediations.append(entry)

    result = {
        "claim_id": claim_id,
        "claim_properties": dict(node_data),
        "claim_level_recovery_properties": recovery_props,
        "remediation_nodes_found": len(summary_remediations),
        "remediations": summary_remediations
    }

    if not summary_remediations and not recovery_props:
        result["note"] = "No remediation, recovery, or resolution nodes found within 3 hops of this claim, and no recovery-related properties on the claim node itself."

    return json.dumps(result, default=str)
