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

        return run_extension_native("get_care_session_device_mismatch", tool_input)

    G = get_graph()

    # Step 1: Find the claim node
    claim_node_id = None
    for nid, data in G.nodes(data=True):
        label = data.get('label', '')
        if label == tool_input['claim_id'] or nid == tool_input['claim_id']:
            claim_node_id = nid
            break
        # Also check properties dict
        props = data.get('properties', {})
        if isinstance(props, dict):
            if props.get('claim_id') == tool_input['claim_id'] or props.get('id') == tool_input['claim_id']:
                claim_node_id = nid
                break

    if claim_node_id is None:
        return json.dumps({'error': f"Claim '{tool_input['claim_id']}' not found in graph.", 'mismatched_sessions': [], 'all_sessions': []})

    # Step 2: Find all CareSession nodes linked to this claim (any direction)
    care_session_ids = set()
    for neighbor in list(G.successors(claim_node_id)) + list(G.predecessors(claim_node_id)):
        ndata = G.nodes[neighbor]
        ntype = ndata.get('node_type', ndata.get('type', ''))
        if 'caresession' in ntype.lower().replace('_', '') or 'care_session' in ntype.lower():
            care_session_ids.add(neighbor)

    if not care_session_ids:
        return json.dumps({'claim_id': tool_input['claim_id'], 'message': 'No CareSession nodes found linked to this claim.', 'mismatched_sessions': [], 'all_sessions': []})

    # Step 3: For each CareSession, extract device info from properties or linked Device nodes
    def get_device_info(session_id):
        sdata = G.nodes[session_id]
        props = sdata.get('properties', {})
        if not isinstance(props, dict):
            props = {}

        # Try direct property keys first
        checkin_device = props.get('check_in_device') or props.get('checkin_device') or props.get('check_in_device_id') or props.get('checkinDevice') or None
        checkout_device = props.get('check_out_device') or props.get('checkout_device') or props.get('check_out_device_id') or props.get('checkoutDevice') or None

        # Also scan all neighbors for Device nodes with CHECKIN / CHECKOUT edge types
        for nbr in G.successors(session_id):
            edge_data = G.get_edge_data(session_id, nbr) or {}
            etype = edge_data.get('edge_type', edge_data.get('type', edge_data.get('label', ''))).upper()
            nbr_type = G.nodes[nbr].get('node_type', G.nodes[nbr].get('type', '')).lower()
            nbr_label = G.nodes[nbr].get('label', nbr)
            if 'checkin' in etype.lower().replace('_','') or 'check_in' in etype.lower():
                checkin_device = checkin_device or nbr_label
            elif 'checkout' in etype.lower().replace('_','') or 'check_out' in etype.lower():
                checkout_device = checkout_device or nbr_label
            elif 'device' in nbr_type:
                # fallback: assign based on any device-like node properties
                nbr_props = G.nodes[nbr].get('properties', {})
                if isinstance(nbr_props, dict):
                    role = nbr_props.get('role', nbr_props.get('usage', '')).lower()
                    if 'checkin' in role.replace('_','') or 'check_in' in role:
                        checkin_device = checkin_device or nbr_label
                    elif 'checkout' in role.replace('_','') or 'check_out' in role:
                        checkout_device = checkout_device or nbr_label

        for nbr in G.predecessors(session_id):
            edge_data = G.get_edge_data(nbr, session_id) or {}
            etype = edge_data.get('edge_type', edge_data.get('type', edge_data.get('label', ''))).upper()
            nbr_label = G.nodes[nbr].get('label', nbr)
            if 'checkin' in etype.lower().replace('_','') or 'check_in' in etype.lower():
                checkin_device = checkin_device or nbr_label
            elif 'checkout' in etype.lower().replace('_','') or 'check_out' in etype.lower():
                checkout_device = checkout_device or nbr_label

        return checkin_device, checkout_device

    all_sessions = []
    mismatched_sessions = []

    for sid in care_session_ids:
        sdata = G.nodes[sid]
        props = sdata.get('properties', {})
        if not isinstance(props, dict):
            props = {}
        session_label = sdata.get('label', sid)
        checkin_device, checkout_device = get_device_info(sid)

        session_info = {
            'session_id': sid,
            'session_label': session_label,
            'check_in_device': checkin_device,
            'check_out_device': checkout_device,
            'devices_match': checkin_device == checkout_device if (checkin_device is not None and checkout_device is not None) else None
        }
        all_sessions.append(session_info)

        # Flag as mismatch if both are known and differ
        if checkin_device is not None and checkout_device is not None and checkin_device != checkout_device:
            mismatched_sessions.append(session_info)

    result = {
        'claim_id': tool_input['claim_id'],
        'total_care_sessions': len(all_sessions),
        'sessions_with_device_mismatch': len(mismatched_sessions),
        'mismatched_sessions': mismatched_sessions,
        'all_sessions': all_sessions
    }
    return json.dumps(result)
