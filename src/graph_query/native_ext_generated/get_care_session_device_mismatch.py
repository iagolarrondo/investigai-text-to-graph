"""get_care_session_device_mismatch

For a given claim_id, traverses to all linked CareSession nodes and compares
the check-in device vs check-out device for each session. Returns sessions
where the two devices differ, along with all session device data.
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json


def run_native(tool_input: dict[str, Any]) -> str:
    claim_id: str = tool_input["claim_id"]

    # ------------------------------------------------------------------
    # Step 1: Locate the claim node by label, node_id, or properties_json
    # ------------------------------------------------------------------
    claim_query = """
        MATCH (c:Entity)
        WHERE c.node_id = $claim_id
           OR c.label   = $claim_id
           OR c.properties_json CONTAINS $claim_id
        RETURN c.node_id   AS node_id,
               c.label     AS label,
               c.node_type AS node_type,
               c.properties_json AS properties_json
        LIMIT 1
    """
    claim_rows = rq(claim_query, {"claim_id": claim_id})

    # Narrow down if multiple candidates: prefer exact label / node_id match
    claim_row = None
    for row in claim_rows:
        props = parse_properties_json(row.get("properties_json", "{}"))
        if (
            row.get("node_id") == claim_id
            or row.get("label") == claim_id
            or props.get("claim_id") == claim_id
            or props.get("id") == claim_id
        ):
            claim_row = row
            break
    if claim_row is None and claim_rows:
        claim_row = claim_rows[0]

    if claim_row is None:
        return json.dumps({
            "error": f"Claim '{claim_id}' not found in graph.",
            "mismatched_sessions": [],
            "all_sessions": [],
        })

    claim_node_id: str = claim_row["node_id"]

    # ------------------------------------------------------------------
    # Step 2: Find all CareSession nodes linked to this claim (any direction)
    # ------------------------------------------------------------------
    care_session_query = """
        MATCH (c:Entity {node_id: $claim_node_id})
        MATCH (c)-[:GRAPH_EDGE]-(s:Entity)
        WHERE toLower(replace(s.node_type, '_', '')) CONTAINS 'caresession'
        RETURN DISTINCT
            s.node_id          AS session_id,
            s.label            AS session_label,
            s.node_type        AS node_type,
            s.properties_json  AS properties_json
        LIMIT 200
    """
    session_rows = rq(care_session_query, {"claim_node_id": claim_node_id})

    if not session_rows:
        return json.dumps({
            "claim_id": claim_id,
            "message": "No CareSession nodes found linked to this claim.",
            "mismatched_sessions": [],
            "all_sessions": [],
        })

    # ------------------------------------------------------------------
    # Step 3: For each CareSession retrieve device info
    #   3a – direct properties on the session node
    #   3b – outgoing edges with CHECKIN / CHECKOUT in edge_type
    #   3c – incoming edges with CHECKIN / CHECKOUT in edge_type
    #   3d – neighbouring Device nodes with a role property
    # ------------------------------------------------------------------
    device_neighbour_query = """
        MATCH (s:Entity {node_id: $session_id})
        // outgoing
        OPTIONAL MATCH (s)-[r_out:GRAPH_EDGE]->(d_out:Entity)
        // incoming
        OPTIONAL MATCH (d_in:Entity)-[r_in:GRAPH_EDGE]->(s)
        RETURN
            d_out.node_id          AS out_node_id,
            d_out.label            AS out_label,
            d_out.node_type        AS out_node_type,
            d_out.properties_json  AS out_properties_json,
            r_out.edge_type        AS out_edge_type,
            d_in.node_id           AS in_node_id,
            d_in.label             AS in_label,
            d_in.node_type         AS in_node_type,
            d_in.properties_json   AS in_properties_json,
            r_in.edge_type         AS in_edge_type
        LIMIT 100
    """

    all_sessions: list[dict] = []
    mismatched_sessions: list[dict] = []

    for sr in session_rows:
        session_id    = sr["session_id"]
        session_label = sr.get("session_label") or session_id
        sess_props    = parse_properties_json(sr.get("properties_json", "{}"))

        # 3a – direct property keys
        checkin_device: str | None = (
            sess_props.get("check_in_device")
            or sess_props.get("checkin_device")
            or sess_props.get("check_in_device_id")
            or sess_props.get("checkinDevice")
            or None
        )
        checkout_device: str | None = (
            sess_props.get("check_out_device")
            or sess_props.get("checkout_device")
            or sess_props.get("check_out_device_id")
            or sess_props.get("checkoutDevice")
            or None
        )

        # 3b / 3c / 3d – graph neighbours
        nbr_rows = rq(device_neighbour_query, {"session_id": session_id})

        for nr in nbr_rows:
            # --- outgoing edge ---
            out_etype = (nr.get("out_edge_type") or "").lower().replace("_", "")
            out_label = nr.get("out_label") or nr.get("out_node_id")
            out_ntype = (nr.get("out_node_type") or "").lower()
            out_props = parse_properties_json(nr.get("out_properties_json", "{}"))

            if out_label:
                if "checkin" in out_etype or "check_in" in out_etype.replace("", ""):
                    checkin_device = checkin_device or out_label
                elif "checkout" in out_etype or "check_out" in out_etype.replace("", ""):
                    checkout_device = checkout_device or out_label
                elif "device" in out_ntype:
                    role = (
                        out_props.get("role", out_props.get("usage", ""))
                    ).lower().replace("_", "")
                    if "checkin" in role:
                        checkin_device = checkin_device or out_label
                    elif "checkout" in role:
                        checkout_device = checkout_device or out_label

            # --- incoming edge ---
            in_etype = (nr.get("in_edge_type") or "").lower().replace("_", "")
            in_label = nr.get("in_label") or nr.get("in_node_id")

            if in_label:
                if "checkin" in in_etype or "check_in" in in_etype.replace("", ""):
                    checkin_device = checkin_device or in_label
                elif "checkout" in in_etype or "check_out" in in_etype.replace("", ""):
                    checkout_device = checkout_device or in_label

        # Determine match status
        if checkin_device is not None and checkout_device is not None:
            devices_match: bool | None = (checkin_device == checkout_device)
        else:
            devices_match = None

        session_info: dict[str, Any] = {
            "session_id":       session_id,
            "session_label":    session_label,
            "check_in_device":  checkin_device,
            "check_out_device": checkout_device,
            "devices_match":    devices_match,
        }
        all_sessions.append(session_info)

        if (
            checkin_device is not None
            and checkout_device is not None
            and checkin_device != checkout_device
        ):
            mismatched_sessions.append(session_info)

    result = {
        "claim_id":                    claim_id,
        "total_care_sessions":         len(all_sessions),
        "sessions_with_device_mismatch": len(mismatched_sessions),
        "mismatched_sessions":         mismatched_sessions,
        "all_sessions":                all_sessions,
    }
    return json.dumps(result)