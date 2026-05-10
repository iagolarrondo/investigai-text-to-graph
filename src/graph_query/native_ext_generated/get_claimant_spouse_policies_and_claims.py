"""get_claimant_spouse_policies_and_claims – Neo4j/Cypher native implementation.

Given a claim_id, locates the claim node, finds the claimant Person node,
detects any spouse via configurable edge-type keywords, then returns the
spouse's policies and claims (excluding the anchor claim).
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _first(records: list[dict], key: str, default=None):
    """Return the value of *key* from the first record, or *default*."""
    return records[0][key] if records else default


# ---------------------------------------------------------------------------
# main entry-point
# ---------------------------------------------------------------------------

def run_native(tool_input: dict[str, Any]) -> str:
    claim_id: str = str(tool_input.get("claim_id", "")).strip()
    if not claim_id:
        return json.dumps({"error": "claim_id is required."})

    spouse_keywords: list[str] = [
        k.lower()
        for k in (tool_input.get("spouse_edge_keywords") or ["spouse", "married", "partner"])
    ]

    # -----------------------------------------------------------------------
    # Step 1: locate the claim node  (exact node_id OR label match first,
    #         then case-insensitive substring fallback)
    # -----------------------------------------------------------------------
    claim_rows = rq(
        """
        MATCH (c:Entity)
        WHERE c.node_id = $cid
           OR c.label   = $cid
           OR (toLower(c.node_type) CONTAINS 'claim' AND c.label = $cid)
        RETURN c.node_id   AS node_id,
               c.label     AS label,
               c.node_type AS node_type
        LIMIT 1
        """,
        {"cid": claim_id},
    )

    if not claim_rows:
        # case-insensitive substring fallback
        claim_rows = rq(
            """
            MATCH (c:Entity)
            WHERE toLower(c.node_id) CONTAINS toLower($cid)
               OR toLower(c.label)   CONTAINS toLower($cid)
            RETURN c.node_id   AS node_id,
                   c.label     AS label,
                   c.node_type AS node_type
            LIMIT 1
            """,
            {"cid": claim_id},
        )

    if not claim_rows:
        return json.dumps(
            {"error": f"Claim node '{claim_id}' not found in graph.",
             "claimant": None,
             "spouse": None}
        )

    claim_node_id: str = claim_rows[0]["node_id"]
    claim_label: str   = claim_rows[0]["label"] or claim_node_id

    # -----------------------------------------------------------------------
    # Step 2: find the claimant Person node (direct neighbour of claim)
    #         Check both directions; filter by node_type containing 'person'
    #         OR edge_type containing 'claimant', 'filed', 'insured'.
    # -----------------------------------------------------------------------
    claimant_rows = rq(
        """
        MATCH (claim:Entity {node_id: $claim_nid})-[r:GRAPH_EDGE]-(person:Entity)
        WHERE toLower(person.node_type) CONTAINS 'person'
           OR toLower(r.edge_type)      CONTAINS 'claimant'
           OR toLower(r.edge_type)      CONTAINS 'filed'
           OR toLower(r.edge_type)      CONTAINS 'insured'
        RETURN person.node_id   AS node_id,
               person.label     AS label,
               person.node_type AS node_type,
               r.edge_type      AS edge_to_claim
        LIMIT 10
        """,
        {"claim_nid": claim_node_id},
    )

    if not claimant_rows:
        return json.dumps(
            {"error": "No Person node found directly linked to claim.",
             "claim_node": claim_node_id,
             "spouse": None}
        )

    claimant = claimant_rows[0]
    claimant_info = {
        "node_id":      claimant["node_id"],
        "label":        claimant["label"] or claimant["node_id"],
        "node_type":    claimant["node_type"],
        "edge_to_claim": claimant["edge_to_claim"],
    }
    claimant_nid: str = claimant_info["node_id"]

    # -----------------------------------------------------------------------
    # Step 3: find spouse(s) of the claimant via keyword-matched edge types.
    #         We pull ALL person-to-person edges (both directions) and filter
    #         in Python so we can apply the dynamic keyword list.
    # -----------------------------------------------------------------------
    spouse_edge_rows = rq(
        """
        MATCH (claimant:Entity {node_id: $cl_nid})-[r:GRAPH_EDGE]-(candidate:Entity)
        WHERE toLower(candidate.node_type) CONTAINS 'person'
           OR candidate.node_type IS NULL
           OR candidate.node_type = ''
        RETURN candidate.node_id   AS node_id,
               candidate.label     AS label,
               candidate.node_type AS node_type,
               r.edge_type         AS edge_type,
               CASE WHEN startNode(r).node_id = $cl_nid
                    THEN 'out' ELSE 'in' END AS direction
        LIMIT 50
        """,
        {"cl_nid": claimant_nid},
    )

    def _is_spouse_edge(etype: str) -> bool:
        el = (etype or "").lower()
        return any(kw in el for kw in spouse_keywords)

    spouse_candidates = [
        {
            "node_id":   r["node_id"],
            "label":     r["label"] or r["node_id"],
            "node_type": r["node_type"],
            "edge_type": r["edge_type"],
            "direction": r["direction"],
        }
        for r in spouse_edge_rows
        if _is_spouse_edge(r["edge_type"])
    ]

    if not spouse_candidates:
        return json.dumps(
            {
                "claim_node":  claim_node_id,
                "claimant":    claimant_info,
                "spouse_found": False,
                "spouse":      None,
                "message":     "No spouse relationship found for the claimant.",
            }
        )

    # Use first spouse found; surface extras.
    primary_spouse = spouse_candidates[0]
    spouse_nid: str = primary_spouse["node_id"]

    spouse_info: dict[str, Any] = {
        "node_id":           spouse_nid,
        "label":             primary_spouse["label"],
        "node_type":         primary_spouse["node_type"],
        "relationship_edge": primary_spouse["edge_type"],
    }
    if len(spouse_candidates) > 1:
        spouse_info["other_spouse_candidates"] = [
            s["node_id"] for s in spouse_candidates[1:]
        ]

    # -----------------------------------------------------------------------
    # Step 4: find policies linked to spouse
    #         Edge keywords: is_covered_by, sold_policy, has_policy,
    #         insured_by, policy  –– OR node_type contains 'policy'.
    # -----------------------------------------------------------------------
    policy_rows = rq(
        """
        MATCH (spouse:Entity {node_id: $sp_nid})-[r:GRAPH_EDGE]-(pol:Entity)
        WHERE toLower(pol.node_type) CONTAINS 'policy'
           OR toLower(r.edge_type)   CONTAINS 'policy'
           OR toLower(r.edge_type)   CONTAINS 'insured'
           OR toLower(r.edge_type)   CONTAINS 'covered'
        RETURN DISTINCT
               pol.node_id   AS node_id,
               pol.label     AS label,
               pol.node_type AS node_type,
               r.edge_type   AS edge_type
        LIMIT 50
        """,
        {"sp_nid": spouse_nid},
    )

    spouse_policies = [
        {
            "policy_node_id": r["node_id"],
            "label":          r["label"] or r["node_id"],
            "node_type":      r["node_type"],
            "edge_type":      r["edge_type"],
        }
        for r in policy_rows
    ]

    # Collect policy node-ids to query claims via policies later.
    policy_nids: list[str] = [p["policy_node_id"] for p in spouse_policies]

    # -----------------------------------------------------------------------
    # Step 5a: find claims DIRECTLY linked to spouse (excluding anchor claim)
    # -----------------------------------------------------------------------
    direct_claim_rows = rq(
        """
        MATCH (spouse:Entity {node_id: $sp_nid})-[r:GRAPH_EDGE]-(cl:Entity)
        WHERE (toLower(cl.node_type) CONTAINS 'claim'
               OR toLower(r.edge_type) CONTAINS 'claim'
               OR toLower(r.edge_type) CONTAINS 'filed'
               OR toLower(r.edge_type) CONTAINS 'claimant')
          AND cl.node_id <> $anchor_claim
        RETURN DISTINCT
               cl.node_id   AS node_id,
               cl.label     AS label,
               cl.node_type AS node_type,
               r.edge_type  AS edge_type
        LIMIT 50
        """,
        {"sp_nid": spouse_nid, "anchor_claim": claim_node_id},
    )

    direct_claims = [
        {
            "claim_node_id": r["node_id"],
            "label":         r["label"] or r["node_id"],
            "node_type":     r["node_type"],
            "edge_type":     r["edge_type"],
        }
        for r in direct_claim_rows
    ]

    # -----------------------------------------------------------------------
    # Step 5b: find claims linked via spouse's policies (excluding anchor)
    # -----------------------------------------------------------------------
    via_policy_claims: list[dict] = []
    if policy_nids:
        via_rows = rq(
            """
            MATCH (pol:Entity)-[r:GRAPH_EDGE]-(cl:Entity)
            WHERE pol.node_id IN $pol_nids
              AND (toLower(cl.node_type) CONTAINS 'claim'
                   OR toLower(r.edge_type) CONTAINS 'claim')
              AND cl.node_id <> $anchor_claim
            RETURN DISTINCT
                   cl.node_id   AS node_id,
                   cl.label     AS label,
                   cl.node_type AS node_type,
                   r.edge_type  AS edge_type,
                   pol.node_id  AS via_policy
            LIMIT 50
            """,
            {"pol_nids": policy_nids, "anchor_claim": claim_node_id},
        )
        via_policy_claims = [
            {
                "claim_node_id": r["node_id"],
                "label":         r["label"] or r["node_id"],
                "node_type":     r["node_type"],
                "edge_type":     r["edge_type"],
                "via_policy":    r["via_policy"],
            }
            for r in via_rows
        ]

    # de-dup all claims (direct wins over via-policy)
    seen_claims: set[str] = set()
    unique_claims: list[dict] = []
    for c in direct_claims + via_policy_claims:
        if c["claim_node_id"] not in seen_claims:
            seen_claims.add(c["claim_node_id"])
            unique_claims.append(c)

    # -----------------------------------------------------------------------
    # Assemble final result
    # -----------------------------------------------------------------------
    result: dict[str, Any] = {
        "claim_node":          claim_node_id,
        "claimant":            claimant_info,
        "spouse_found":        True,
        "spouse":              spouse_info,
        "spouse_policies":     spouse_policies,
        "spouse_policies_count": len(spouse_policies),
        "spouse_claims":       unique_claims,
        "spouse_claims_count": len(unique_claims),
        "summary": (
            f"Claimant {claimant_info['label']} has a spouse: "
            f"{spouse_info['label']}. "
            f"Spouse has {len(spouse_policies)} policy(ies) and "
            f"{len(unique_claims)} claim(s) (excluding the anchor claim)."
        ),
    }
    return json.dumps(result)