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

        return run_extension_native("get_claim_payment_bank_accounts", tool_input)

    G = get_graph()
    claim_id = tool_input.get("claim_id", "").strip()

    # Resolve claim node
    claim_node = None
    if claim_id in G.nodes:
        claim_node = claim_id
    else:
        for nid, data in G.nodes(data=True):
            label = str(data.get("label", ""))
            props = str(data)
            if claim_id in label or claim_id in props:
                if data.get("node_type", "").lower() in ("claim", "") or "claim" in label.lower() or "CLM" in label:
                    claim_node = nid
                    break
        if claim_node is None:
            for nid, data in G.nodes(data=True):
                label = str(data.get("label", ""))
                if claim_id in label or claim_id in str(data):
                    claim_node = nid
                    break

    if claim_node is None:
        return json.dumps({"error": f"Claim node not found for id: {claim_id}", "bank_accounts": []})

    claim_data = G.nodes[claim_node]

    # Find Payment nodes linked to the claim (any direction)
    payment_nodes = []
    neighbors = list(G.successors(claim_node)) + list(G.predecessors(claim_node))
    for nid in neighbors:
        ndata = G.nodes[nid]
        ntype = str(ndata.get("node_type", "")).lower()
        nlabel = str(ndata.get("label", "")).lower()
        if "payment" in ntype or "payment" in nlabel:
            payment_nodes.append(nid)

    if not payment_nodes:
        return json.dumps({
            "claim_id": claim_node,
            "claim_label": claim_data.get("label", claim_node),
            "payment_nodes": [],
            "bank_accounts": [],
            "message": "No Payment nodes found linked to this claim."
        })

    # Find BankAccount nodes linked to each payment
    bank_accounts = {}
    payment_summary = []
    for pnid in payment_nodes:
        pdata = G.nodes[pnid]
        ba_for_payment = []
        p_neighbors = list(G.successors(pnid)) + list(G.predecessors(pnid))
        for bnid in p_neighbors:
            bdata = G.nodes[bnid]
            btype = str(bdata.get("node_type", "")).lower()
            blabel = str(bdata.get("label", "")).lower()
            if "bank" in btype or "bank" in blabel or "account" in btype:
                ba_entry = {
                    "bank_account_id": bnid,
                    "label": bdata.get("label", bnid),
                    "node_type": bdata.get("node_type", "unknown")
                }
                # Add any useful properties
                for k, v in bdata.items():
                    if k not in ("label", "node_type") and not k.startswith("_"):
                        ba_entry[k] = v
                ba_for_payment.append(ba_entry)
                bank_accounts[bnid] = ba_entry
        payment_summary.append({
            "payment_id": pnid,
            "label": pdata.get("label", pnid),
            "node_type": pdata.get("node_type", "unknown"),
            "bank_accounts": ba_for_payment
        })

    return json.dumps({
        "claim_id": claim_node,
        "claim_label": claim_data.get("label", claim_node),
        "payment_count": len(payment_nodes),
        "payments": payment_summary,
        "bank_account_count": len(bank_accounts),
        "bank_accounts": list(bank_accounts.values())
    })
