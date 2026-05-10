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

        return run_extension_native("get_claimant_spouse_policies_and_claims", tool_input)

    G = get_graph()
    claim_id = tool_input.get("claim_id", "").strip()
    spouse_keywords = tool_input.get("spouse_edge_keywords") or ["spouse", "married", "partner"]
    spouse_keywords_lower = [k.lower() for k in spouse_keywords]

    # --- Step 1: locate the claim node ---
    claim_node = None
    for nid, data in G.nodes(data=True):
        label = data.get("label", "") or ""
        ntype = data.get("node_type", "") or ""
        if nid == claim_id or label == claim_id or ("Claim" in ntype and label == claim_id):
            claim_node = nid
            break
    # fallback: case-insensitive substring
    if claim_node is None:
        for nid, data in G.nodes(data=True):
            label = str(data.get("label", "") or "")
            if claim_id.lower() in label.lower() or claim_id.lower() in str(nid).lower():
                claim_node = nid
                break
    if claim_node is None:
        return json.dumps({"error": f"Claim node '{claim_id}' not found in graph.", "claimant": None, "spouse": None})

    # --- Step 2: find the claimant Person node (direct neighbours of claim) ---
    claimant_nodes = []
    for src, dst, edata in G.out_edges(claim_node, data=True):
        etype = str(edata.get("edge_type", edata.get("label", "")) or "").lower()
        ntype = str(G.nodes[dst].get("node_type", "") or "").lower()
        if "person" in ntype or "claimant" in etype or "filed" in etype or "insured" in etype:
            claimant_nodes.append((dst, edata.get("edge_type", edata.get("label", ""))))
    for src, dst, edata in G.in_edges(claim_node, data=True):
        etype = str(edata.get("edge_type", edata.get("label", "")) or "").lower()
        ntype = str(G.nodes[src].get("node_type", "") or "").lower()
        if "person" in ntype or "claimant" in etype or "filed" in etype or "insured" in etype:
            claimant_nodes.append((src, edata.get("edge_type", edata.get("label", ""))))
    # de-dup while preserving order
    seen = set()
    unique_claimants = []
    for item in claimant_nodes:
        if item[0] not in seen:
            seen.add(item[0])
            unique_claimants.append(item)
    claimant_nodes = unique_claimants

    if not claimant_nodes:
        return json.dumps({"error": "No Person node found directly linked to claim.", "claim_node": claim_node, "spouse": None})

    # Use first claimant found
    claimant_id, claimant_edge = claimant_nodes[0]
    claimant_data = G.nodes[claimant_id]
    claimant_info = {
        "node_id": claimant_id,
        "label": claimant_data.get("label", claimant_id),
        "node_type": claimant_data.get("node_type", ""),
        "edge_to_claim": claimant_edge
    }

    # --- Step 3: find spouse of claimant ---
    def is_spouse_edge(etype_str):
        el = etype_str.lower()
        return any(kw in el for kw in spouse_keywords_lower)

    spouse_candidates = []
    for src, dst, edata in G.out_edges(claimant_id, data=True):
        etype = str(edata.get("edge_type", edata.get("label", "")) or "")
        if is_spouse_edge(etype):
            ntype = str(G.nodes[dst].get("node_type", "") or "").lower()
            if "person" in ntype or ntype == "":
                spouse_candidates.append({"node_id": dst, "edge_type": etype, "direction": "out"})
    for src, dst, edata in G.in_edges(claimant_id, data=True):
        etype = str(edata.get("edge_type", edata.get("label", "")) or "")
        if is_spouse_edge(etype):
            ntype = str(G.nodes[src].get("node_type", "") or "").lower()
            if "person" in ntype or ntype == "":
                spouse_candidates.append({"node_id": src, "edge_type": etype, "direction": "in"})

    if not spouse_candidates:
        return json.dumps({
            "claim_node": claim_node,
            "claimant": claimant_info,
            "spouse_found": False,
            "spouse": None,
            "message": "No spouse relationship found for the claimant."
        })

    # Use first spouse
    spouse_entry = spouse_candidates[0]
    spouse_id = spouse_entry["node_id"]
    spouse_data = G.nodes[spouse_id]
    spouse_info = {
        "node_id": spouse_id,
        "label": spouse_data.get("label", spouse_id),
        "node_type": spouse_data.get("node_type", ""),
        "relationship_edge": spouse_entry["edge_type"]
    }
    if len(spouse_candidates) > 1:
        spouse_info["other_spouse_candidates"] = [s["node_id"] for s in spouse_candidates[1:]]

    # --- Step 4: find policies linked to spouse ---
    policy_edges = ["is_covered_by", "sold_policy", "has_policy", "insured_by", "policy"]
    spouse_policies = []
    for src, dst, edata in G.out_edges(spouse_id, data=True):
        etype = str(edata.get("edge_type", edata.get("label", "")) or "").lower()
        ntype = str(G.nodes[dst].get("node_type", "") or "").lower()
        if any(pe in etype for pe in policy_edges) or "policy" in ntype:
            spouse_policies.append({
                "policy_node_id": dst,
                "label": G.nodes[dst].get("label", dst),
                "node_type": G.nodes[dst].get("node_type", ""),
                "edge_type": edata.get("edge_type", edata.get("label", ""))
            })
    for src, dst, edata in G.in_edges(spouse_id, data=True):
        etype = str(edata.get("edge_type", edata.get("label", "")) or "").lower()
        ntype = str(G.nodes[src].get("node_type", "") or "").lower()
        if any(pe in etype for pe in policy_edges) or "policy" in ntype:
            spouse_policies.append({
                "policy_node_id": src,
                "label": G.nodes[src].get("label", src),
                "node_type": G.nodes[src].get("node_type", ""),
                "edge_type": edata.get("edge_type", edata.get("label", ""))
            })
    # de-dup
    seen_pol = set()
    unique_policies = []
    for p in spouse_policies:
        if p["policy_node_id"] not in seen_pol:
            seen_pol.add(p["policy_node_id"])
            unique_policies.append(p)
    spouse_policies = unique_policies

    # --- Step 5: find claims linked to spouse ---
    claim_edges = ["filed", "claim", "has_claim", "claimant"]
    spouse_claims = []
    for src, dst, edata in G.out_edges(spouse_id, data=True):
        etype = str(edata.get("edge_type", edata.get("label", "")) or "").lower()
        ntype = str(G.nodes[dst].get("node_type", "") or "").lower()
        if any(ce in etype for ce in claim_edges) or "claim" in ntype:
            if dst != claim_node:
                spouse_claims.append({
                    "claim_node_id": dst,
                    "label": G.nodes[dst].get("label", dst),
                    "node_type": G.nodes[dst].get("node_type", ""),
                    "edge_type": edata.get("edge_type", edata.get("label", ""))
                })
    for src, dst, edata in G.in_edges(spouse_id, data=True):
        etype = str(edata.get("edge_type", edata.get("label", "")) or "").lower()
        ntype = str(G.nodes[src].get("node_type", "") or "").lower()
        if any(ce in etype for ce in claim_edges) or "claim" in ntype:
            if src != claim_node:
                spouse_claims.append({
                    "claim_node_id": src,
                    "label": G.nodes[src].get("label", src),
                    "node_type": G.nodes[src].get("node_type", ""),
                    "edge_type": edata.get("edge_type", edata.get("label", ""))
                })
    # also check policies of spouse for claims
    for pol in spouse_policies:
        pol_id = pol["policy_node_id"]
        for src, dst, edata in G.out_edges(pol_id, data=True):
            etype = str(edata.get("edge_type", edata.get("label", "")) or "").lower()
            ntype = str(G.nodes[dst].get("node_type", "") or "").lower()
            if "claim" in ntype or "claim" in etype:
                spouse_claims.append({
                    "claim_node_id": dst,
                    "label": G.nodes[dst].get("label", dst),
                    "node_type": G.nodes[dst].get("node_type", ""),
                    "edge_type": edata.get("edge_type", edata.get("label", "")),
                    "via_policy": pol_id
                })
        for src, dst, edata in G.in_edges(pol_id, data=True):
            etype = str(edata.get("edge_type", edata.get("label", "")) or "").lower()
            ntype = str(G.nodes[src].get("node_type", "") or "").lower()
            if "claim" in ntype or "claim" in etype:
                spouse_claims.append({
                    "claim_node_id": src,
                    "label": G.nodes[src].get("label", src),
                    "node_type": G.nodes[src].get("node_type", ""),
                    "edge_type": edata.get("edge_type", edata.get("label", "")),
                    "via_policy": pol_id
                })
    # de-dup claims
    seen_cl = set()
    unique_claims = []
    for c in spouse_claims:
        if c["claim_node_id"] not in seen_cl:
            seen_cl.add(c["claim_node_id"])
            unique_claims.append(c)
    spouse_claims = unique_claims

    result = {
        "claim_node": claim_node,
        "claimant": claimant_info,
        "spouse_found": True,
        "spouse": spouse_info,
        "spouse_policies": spouse_policies,
        "spouse_policies_count": len(spouse_policies),
        "spouse_claims": spouse_claims,
        "spouse_claims_count": len(spouse_claims),
        "summary": (
            f"Claimant {claimant_info['label']} has a spouse: {spouse_info['label']}. "
            f"Spouse has {len(spouse_policies)} policy(ies) and {len(spouse_claims)} claim(s) (excluding the anchor claim)."
        )
    }
    return json.dumps(result)
