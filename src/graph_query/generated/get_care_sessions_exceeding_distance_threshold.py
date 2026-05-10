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

        return run_extension_native("get_care_sessions_exceeding_distance_threshold", tool_input)

    import math

    threshold = float(tool_input.get('distance_threshold_miles', 5.0))
    claim_id = tool_input.get('claim_id', '').strip()

    if not claim_id:
        return json.dumps({'error': 'claim_id is required'})

    G = get_graph()

    # --- Locate the claim node ---
    claim_node = None
    for n, data in G.nodes(data=True):
        if n == claim_id or data.get('label') == claim_id or str(data.get('claim_id', '')) == claim_id:
            claim_node = n
            break
    if claim_node is None:
        return json.dumps({'error': f'Claim node not found for id: {claim_id}', 'sessions_exceeding_threshold': []})

    # --- Find insured Person node via neighbors ---
    insured_node = None
    insured_props = {}
    # Check outgoing and incoming edges for person/insured links
    for src, dst, edata in list(G.out_edges(claim_node, data=True)) + list(G.in_edges(claim_node, data=True)):
        other = dst if src == claim_node else src
        other_data = G.nodes[other]
        ntype = other_data.get('node_type', '')
        rel = edata.get('edge_type', edata.get('relationship', edata.get('type', '')))
        if ntype in ('Person', 'Insured') or 'insured' in rel.lower() or 'covered' in rel.lower():
            insured_node = other
            insured_props = other_data
            break
    # Broader fallback: any Person node linked within 2 hops
    if insured_node is None:
        for src, dst, edata in list(G.out_edges(claim_node, data=True)) + list(G.in_edges(claim_node, data=True)):
            other = dst if src == claim_node else src
            other_data = G.nodes[other]
            if other_data.get('node_type') == 'Person':
                insured_node = other
                insured_props = other_data
                break

    # --- Extract insured lat/lon ---
    def extract_latlon(props):
        lat, lon = None, None
        for k, v in props.items():
            kl = k.lower()
            if 'lat' in kl and 'lon' not in kl:
                try: lat = float(v)
                except (TypeError, ValueError): pass
            elif 'lon' in kl or 'lng' in kl:
                try: lon = float(v)
                except (TypeError, ValueError): pass
        return lat, lon

    def haversine(lat1, lon1, lat2, lon2):
        R = 3958.8  # Earth radius in miles
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    ins_lat, ins_lon = None, None
    if insured_node is not None:
        ins_lat, ins_lon = extract_latlon(insured_props)
        # Try linked Address node if no lat/lon on Person
        if ins_lat is None or ins_lon is None:
            for src, dst, edata in list(G.out_edges(insured_node, data=True)) + list(G.in_edges(insured_node, data=True)):
                other = dst if src == insured_node else src
                other_data = G.nodes[other]
                if other_data.get('node_type') in ('Address', 'Location'):
                    ins_lat, ins_lon = extract_latlon(other_data)
                    if ins_lat is not None and ins_lon is not None:
                        break

    # --- Find all CareSession nodes linked to the claim ---
    care_sessions = []
    visited = set()
    def find_care_sessions(node, depth=0):
        if depth > 2 or node in visited:
            return
        visited.add(node)
        for src, dst, edata in list(G.out_edges(node, data=True)) + list(G.in_edges(node, data=True)):
            other = dst if src == node else src
            if other in visited:
                continue
            other_data = G.nodes[other]
            ntype = other_data.get('node_type', '')
            if 'caresession' in ntype.lower() or 'care_session' in ntype.lower() or ntype == 'CareSession':
                if other not in [s['node_id'] for s in care_sessions]:
                    care_sessions.append({'node_id': other, 'props': dict(other_data)})
            elif depth < 1:
                find_care_sessions(other, depth + 1)
    find_care_sessions(claim_node)

    if not care_sessions:
        return json.dumps({
            'claim_id': claim_id,
            'insured_node': insured_node,
            'insured_lat': ins_lat,
            'insured_lon': ins_lon,
            'threshold_miles': threshold,
            'sessions_exceeding_threshold': [],
            'total_sessions_found': 0,
            'note': 'No CareSession nodes found linked to this claim.'
        })

    # --- Evaluate each session's distance ---
    all_session_results = []
    sessions_exceeding = []

    for session in care_sessions:
        sid = session['node_id']
        props = session['props']
        # Try to get lat/lon from session properties
        s_lat, s_lon = extract_latlon(props)
        # Also check linked Location/Address nodes
        if s_lat is None or s_lon is None:
            for src, dst, edata in list(G.out_edges(sid, data=True)) + list(G.in_edges(sid, data=True)):
                other = dst if src == sid else src
                other_data = G.nodes[other]
                if other_data.get('node_type') in ('Address', 'Location', 'Ping', 'GpsLocation'):
                    s_lat, s_lon = extract_latlon(other_data)
                    if s_lat is not None and s_lon is not None:
                        break

        distance_miles = None
        distance_method = 'unavailable'
        if ins_lat is not None and ins_lon is not None and s_lat is not None and s_lon is not None:
            distance_miles = round(haversine(ins_lat, ins_lon, s_lat, s_lon), 4)
            distance_method = 'haversine'
        elif ins_lat is None or ins_lon is None:
            distance_method = 'no_insured_coords'
        else:
            distance_method = 'no_session_coords'

        session_summary = {
            'session_id': sid,
            'session_label': props.get('label', props.get('session_id', sid)),
            'session_lat': s_lat,
            'session_lon': s_lon,
            'distance_miles': distance_miles,
            'distance_method': distance_method,
            'exceeds_threshold': distance_miles is not None and distance_miles > threshold,
            'props_snapshot': {k: v for k, v in props.items() if k not in ('label',) and not k.startswith('_')}
        }
        all_session_results.append(session_summary)
        if distance_miles is not None and distance_miles > threshold:
            sessions_exceeding.append(session_summary)

    all_session_results.sort(key=lambda x: (x['distance_miles'] is None, -(x['distance_miles'] or 0)))

    return json.dumps({
        'claim_id': claim_id,
        'insured_node': insured_node,
        'insured_lat': ins_lat,
        'insured_lon': ins_lon,
        'threshold_miles': threshold,
        'total_sessions_found': len(care_sessions),
        'sessions_exceeding_threshold': sessions_exceeding,
        'count_exceeding_threshold': len(sessions_exceeding),
        'all_sessions_ranked_by_distance': all_session_results
    })
