"""get_claim_icp_policyholder_address_comparison

Given a claim_id, traverses Claim → ICP and Claim → Policy → Policyholder
to retrieve home address properties for both parties, returning them
side-by-side with a boolean shared_address flag.
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_props(raw) -> dict:
    """Safely parse a properties_json field into a dict."""
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    try:
        return parse_properties_json(raw)
    except Exception:
        pass
    try:
        return json.loads(raw)
    except Exception:
        return {}


_ADDRESS_KEYS = frozenset([
    'address', 'home_address', 'street', 'street_address',
    'city', 'state', 'zip', 'zip_code', 'postal_code', 'full_address',
])


def _extract_address_fields(props: dict) -> dict:
    """Return only address-related keys from a properties dict."""
    return {
        k: v for k, v in props.items()
        if k.lower() in _ADDRESS_KEYS or 'address' in k.lower()
    }


def _normalize_addr(addr_dict: dict) -> str:
    """Produce a lowercased, stripped, sorted-key string for comparison."""
    if not addr_dict:
        return ''
    parts = []
    for k in sorted(addr_dict.keys()):
        v = str(addr_dict[k]).strip().lower()
        if v:
            parts.append(v)
    return '|'.join(parts)


def _addresses_match(ph_addr: dict, icp_addr: dict) -> bool:
    """Return True if addresses are considered equal (exact or partial key match)."""
    if not ph_addr or not icp_addr:
        return False
    ph_norm = _normalize_addr(ph_addr)
    icp_norm = _normalize_addr(icp_addr)
    if ph_norm and icp_norm and ph_norm == icp_norm:
        return True
    # partial match on common address fields
    for key in ('address', 'full_address', 'home_address', 'street_address'):
        ph_val = str(ph_addr.get(key, '')).strip().lower()
        icp_val = str(icp_addr.get(key, '')).strip().lower()
        if ph_val and icp_val and ph_val == icp_val:
            return True
    return False


# ---------------------------------------------------------------------------
# Address resolution helpers using Cypher
# ---------------------------------------------------------------------------

def _get_address_from_neighbors(node_id: str) -> dict:
    """
    Look for neighbouring Address-type nodes (in either direction).
    If found, merge their properties; otherwise return empty dict.
    """
    cypher = """
    MATCH (n {node_id: $node_id})
    OPTIONAL MATCH (n)-[:GRAPH_EDGE]-(addr)
    WHERE toLower(addr.node_type) CONTAINS 'address'
    RETURN
        addr.node_id        AS addr_node_id,
        addr.label          AS addr_label,
        addr.properties_json AS addr_props
    LIMIT 10
    """
    rows = rq(cypher, {"node_id": node_id})
    addr_data: dict = {}
    for row in rows:
        if row.get("addr_node_id") is None:
            continue
        props = _parse_props(row.get("addr_props"))
        for k, v in props.items():
            if k not in ('node_type', 'type', 'id', 'node_id'):
                addr_data[k] = v
        # also capture the label if it looks like an address string
        if row.get("addr_label") and "addr_label" not in addr_data:
            addr_data["label"] = row["addr_label"]
    return addr_data


def _get_node_address(node_id: str, node_props: dict) -> dict:
    """
    Return address dict for a given node:
    1. Try address-type neighbour nodes.
    2. Fall back to address fields on the node itself.
    """
    addr = _get_address_from_neighbors(node_id)
    if not addr:
        addr = _extract_address_fields(node_props)
    return addr


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_native(tool_input: dict[str, Any]) -> str:
    claim_id: str = tool_input["claim_id"]

    # ------------------------------------------------------------------
    # 1. Locate the claim node
    # ------------------------------------------------------------------
    claim_cypher = """
    MATCH (c:Entity)
    WHERE c.label = $claim_id
       OR c.node_id = $claim_id
       OR (toLower(c.label) CONTAINS toLower($claim_id)
           AND toLower(c.node_type) CONTAINS 'claim')
    RETURN c.node_id AS node_id,
           c.label   AS label,
           c.node_type AS node_type,
           c.properties_json AS props
    LIMIT 5
    """
    claim_rows = rq(claim_cypher, {"claim_id": claim_id})
    if not claim_rows:
        return json.dumps({"error": f"Claim '{claim_id}' not found in graph."})

    claim_row = claim_rows[0]
    claim_node_id: str = claim_row["node_id"]

    # ------------------------------------------------------------------
    # 2. Find ICP nodes directly linked to the claim (either direction)
    # ------------------------------------------------------------------
    icp_cypher = """
    MATCH (c:Entity {node_id: $claim_node_id})
    MATCH (c)-[:GRAPH_EDGE]-(icp:Entity)
    WHERE toLower(icp.node_type) CONTAINS 'icp'
       OR toLower(icp.node_type) CONTAINS 'independentcare'
       OR toLower(icp.node_type) CONTAINS 'independent_care'
       OR toLower(icp.node_type) CONTAINS 'careprovider'
    RETURN DISTINCT
        icp.node_id         AS node_id,
        icp.label           AS label,
        icp.node_type       AS node_type,
        icp.properties_json AS props
    LIMIT 20
    """
    icp_rows = rq(icp_cypher, {"claim_node_id": claim_node_id})

    # ------------------------------------------------------------------
    # 3. Find Policy node linked to the claim (either direction)
    # ------------------------------------------------------------------
    policy_cypher = """
    MATCH (c:Entity {node_id: $claim_node_id})
    MATCH (c)-[:GRAPH_EDGE]-(pol:Entity)
    WHERE toLower(pol.node_type) CONTAINS 'policy'
    RETURN DISTINCT
        pol.node_id         AS node_id,
        pol.label           AS label,
        pol.node_type       AS node_type,
        pol.properties_json AS props
    LIMIT 5
    """
    policy_rows = rq(policy_cypher, {"claim_node_id": claim_node_id})

    policy_node_id: str | None = policy_rows[0]["node_id"] if policy_rows else None

    # ------------------------------------------------------------------
    # 4. Find Policyholder/Insured Person from the Policy
    # ------------------------------------------------------------------
    policyholder_row: dict | None = None
    policyholder_role: str | None = None

    if policy_node_id:
        ph_cypher = """
        MATCH (pol:Entity {node_id: $policy_node_id})
        MATCH (pol)-[r:GRAPH_EDGE]-(ph:Entity)
        WHERE toLower(ph.node_type) CONTAINS 'person'
           OR toLower(ph.node_type) CONTAINS 'insured'
           OR toLower(ph.node_type) CONTAINS 'customer'
        RETURN DISTINCT
            ph.node_id             AS node_id,
            ph.label               AS label,
            ph.node_type           AS node_type,
            ph.properties_json     AS props,
            r.edge_type            AS edge_type
        LIMIT 10
        """
        ph_rows = rq(ph_cypher, {"policy_node_id": policy_node_id})

        # prefer rows whose edge_type matches holder/covered/insured/owner
        for row in ph_rows:
            et = str(row.get("edge_type") or "").lower()
            if any(kw in et for kw in ('covered', 'holder', 'insured', 'owner')):
                policyholder_row = row
                policyholder_role = et or "unknown"
                break
        if policyholder_row is None and ph_rows:
            policyholder_row = ph_rows[0]
            policyholder_role = str(ph_rows[0].get("edge_type") or "unknown").lower()

    # ------------------------------------------------------------------
    # 5. Resolve addresses
    # ------------------------------------------------------------------
    notes: list[str] = []

    if policy_node_id is None:
        notes.append("No Policy node found linked to this claim.")
    if not icp_rows:
        notes.append("No ICP node found linked to this claim.")
    if policyholder_row is None:
        notes.append("No Policyholder/Insured Person found on the policy.")

    # Policyholder address
    ph_addr: dict = {}
    policyholder_info: dict | None = None
    if policyholder_row:
        ph_props = _parse_props(policyholder_row.get("props"))
        ph_addr = _get_node_address(policyholder_row["node_id"], ph_props)
        policyholder_info = {
            "node_id": policyholder_row["node_id"],
            "label":   policyholder_row["label"],
            "role":    policyholder_role,
            "address": ph_addr,
        }
        if not ph_addr:
            notes.append("Policyholder address properties not found in graph.")

    # ICP addresses
    icps_result: list[dict] = []
    any_shared = False

    for icp_row in icp_rows:
        icp_props = _parse_props(icp_row.get("props"))
        icp_addr = _get_node_address(icp_row["node_id"], icp_props)
        shared = _addresses_match(ph_addr, icp_addr)
        if shared:
            any_shared = True
        icps_result.append({
            "node_id": icp_row["node_id"],
            "label":   icp_row["label"],
            "address": icp_addr,
            "shared_address_with_policyholder": shared,
        })

    if icp_rows and all(not icp["address"] for icp in icps_result):
        notes.append("ICP address properties not found in graph.")

    # ------------------------------------------------------------------
    # 6. Assemble result
    # ------------------------------------------------------------------
    result = {
        "claim_id":      claim_id,
        "claim_node_id": claim_node_id,
        "icp_count":     len(icps_result),
        "icps":          icps_result,
        "policyholder":  policyholder_info,
        "shared_address": any_shared,
        "notes":         notes,
    }
    return json.dumps(result)