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

        return run_extension_native("get_care_sessions_by_distance_from_insured", tool_input)

    import math

    def haversine(lat1, lon1, lat2, lon2):
        R = 3958.8  # Earth radius in miles
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def try_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def extract_lat_lon(node):
        props = node.get('properties', {})
        lat = try_float(props.get('latitude') or props.get('lat'))
        lon = try_float(props.get('longitude') or props.get('lon') or props.get('lng'))
        return lat, lon

    def extract_address_str(node):
        props = node.get('properties', {})
        parts = []
        for key in ['address', 'street', 'street_address', 'city', 'state', 'zip', 'zip_code', 'full_address']:
            v = props.get(key)
            if v:
                parts.append(str(v))
        label = node.get('label', '')
        if label:
            parts.insert(0, label)
        return ', '.join(parts) if parts else str(props)

    G = get_graph()
    claim_id = tool_input.get('claim_id', '').strip()

    # Step 1: Locate the claim node
    claim_node = None
    for nid, data in G.nodes(data=True):
        if nid == claim_id or data.get('label') == claim_id:
            claim_node = (nid, data)
            break
        props = data.get('properties', {})
        if props.get('claim_id') == claim_id or props.get('claim_number') == claim_id:
            claim_node = (nid, data)
            break

    if claim_node is None:
        return json.dumps({'error': f'Claim not found: {claim_id}', 'claim_id': claim_id})

    claim_nid, claim_data = claim_node

    # Step 2: Find insured Person node and CareSession nodes from claim neighborhood
    # Collect all neighbors (undirected)
    neighbors = set(G.successors(claim_nid)) | set(G.predecessors(claim_nid))

    insured_node = None
    care_session_nids = []

    for nbr in neighbors:
        nbr_data = G.nodes[nbr]
        ntype = nbr_data.get('node_type', nbr_data.get('type', ''))
        # Find insured person
        if ntype in ('Person', 'Insured', 'Customer') and insured_node is None:
            # Prefer nodes connected via IS_INSURED / INSURED_BY / HAS_INSURED edge
            edge_data_fwd = G.get_edge_data(claim_nid, nbr) or {}
            edge_data_bwd = G.get_edge_data(nbr, claim_nid) or {}
            rel_fwd = edge_data_fwd.get('relationship', edge_data_fwd.get('edge_type', edge_data_fwd.get('label', '')))
            rel_bwd = edge_data_bwd.get('relationship', edge_data_bwd.get('edge_type', edge_data_bwd.get('label', '')))
            rel = (rel_fwd or rel_bwd or '').upper()
            if any(kw in rel for kw in ('INSUR', 'CLAIMANT', 'COVERED', 'PERSON', 'FILED')):
                insured_node = (nbr, nbr_data)
            elif insured_node is None and ntype in ('Person', 'Insured', 'Customer'):
                insured_node = (nbr, nbr_data)  # fallback
        if 'CARE' in ntype.upper() or 'SESSION' in ntype.upper():
            care_session_nids.append(nbr)

    # If no insured found yet, do a 2-hop search through policy
    if insured_node is None:
        for nbr in neighbors:
            nbr_data = G.nodes[nbr]
            ntype = nbr_data.get('node_type', nbr_data.get('type', ''))
            if 'POLICY' in ntype.upper() or 'POLIC' in ntype.upper():
                for nbr2 in set(G.successors(nbr)) | set(G.predecessors(nbr)):
                    nd2 = G.nodes[nbr2]
                    nt2 = nd2.get('node_type', nd2.get('type', ''))
                    if nt2 in ('Person', 'Insured', 'Customer'):
                        insured_node = (nbr2, nd2)
                        break
            if insured_node:
                break

    # Also search 2-hop for care sessions if none found directly
    if not care_session_nids:
        for nbr in neighbors:
            nbr_data = G.nodes[nbr]
            ntype = nbr_data.get('node_type', nbr_data.get('type', ''))
            for nbr2 in set(G.successors(nbr)) | set(G.predecessors(nbr)):
                nd2 = G.nodes[nbr2]
                nt2 = nd2.get('node_type', nd2.get('type', ''))
                if 'CARE' in nt2.upper() or 'SESSION' in nt2.upper():
                    if nbr2 not in care_session_nids:
                        care_session_nids.append(nbr2)

    # Step 3: Get insured's address node
    insured_addr = None
    insured_lat, insured_lon = None, None
    insured_addr_str = None

    if insured_node:
        ins_nid, ins_data = insured_node
        # Try lat/lon directly on person node
        insured_lat, insured_lon = extract_lat_lon(ins_data)
        # Look for address neighbors
        ins_neighbors = set(G.successors(ins_nid)) | set(G.predecessors(ins_nid))
        for anid in ins_neighbors:
            an_data = G.nodes[anid]
            an_type = an_data.get('node_type', an_data.get('type', ''))
            if 'ADDR' in an_type.upper() or 'LOCATION' in an_type.upper():
                insured_addr = (anid, an_data)
                lat, lon = extract_lat_lon(an_data)
                if lat is not None and lon is not None:
                    insured_lat, insured_lon = lat, lon
                insured_addr_str = extract_address_str(an_data)
                break
        if insured_addr_str is None:
            insured_addr_str = extract_address_str(ins_data)
        if insured_lat is None:
            # Try person props
            ins_props = ins_data.get('properties', {})
            insured_addr_str = insured_addr_str or ins_props.get('address', '')

    # Step 4: For each CareSession, find check-out location
    sessions_info = []
    for cs_nid in care_session_nids:
        cs_data = G.nodes[cs_nid]
        cs_props = cs_data.get('properties', {})
        cs_label = cs_data.get('label', cs_nid)

        checkout_lat, checkout_lon = None, None
        checkout_addr_str = None
        checkout_node_id = None

        # Check session node itself for checkout lat/lon
        for key_lat in ['checkout_lat', 'check_out_lat', 'checkout_latitude', 'checkin_lat']:
            v = try_float(cs_props.get(key_lat))
            if v is not None:
                checkout_lat = v
                break
        for key_lon in ['checkout_lon', 'check_out_lon', 'checkout_longitude', 'checkin_lon']:
            v = try_float(cs_props.get(key_lon))
            if v is not None:
                checkout_lon = v
                break

        # Also check for checkout_address string on session node
        for key_addr in ['checkout_address', 'check_out_address', 'location', 'address']:
            v = cs_props.get(key_addr)
            if v:
                checkout_addr_str = str(v)
                break

        # Traverse neighbors of care session to find checkout/address nodes
        cs_neighbors = set(G.successors(cs_nid)) | set(G.predecessors(cs_nid))
        for cnid in cs_neighbors:
            cn_data = G.nodes[cnid]
            cn_type = cn_data.get('node_type', cn_data.get('type', ''))
            cn_label_val = cn_data.get('label', '')
            edge_fwd = G.get_edge_data(cs_nid, cnid) or {}
            edge_bwd = G.get_edge_data(cnid, cs_nid) or {}
            edge_rel = (edge_fwd.get('relationship', edge_fwd.get('edge_type', edge_fwd.get('label', ''))) or
                        edge_bwd.get('relationship', edge_bwd.get('edge_type', edge_bwd.get('label', '')))).upper()

            is_checkout = 'CHECKOUT' in edge_rel or 'CHECK_OUT' in edge_rel or 'CHECKOUT' in cn_type.upper()
            is_addr = 'ADDR' in cn_type.upper() or 'LOCATION' in cn_type.upper()

            if is_checkout or is_addr:
                lat, lon = extract_lat_lon(cn_data)
                if lat is not None and lon is not None and checkout_lat is None:
                    checkout_lat = lat
                    checkout_lon = lon
                    checkout_node_id = cnid
                if checkout_addr_str is None:
                    checkout_addr_str = extract_address_str(cn_data)
                    checkout_node_id = cnid

        # Compute distance
        distance = None
        distance_method = 'none'
        if (insured_lat is not None and insured_lon is not None and
                checkout_lat is not None and checkout_lon is not None):
            distance = haversine(insured_lat, insured_lon, checkout_lat, checkout_lon)
            distance_method = 'haversine_miles'
        elif insured_addr_str and checkout_addr_str:
            # No coordinates: use string inequality as proxy (non-match = some distance)
            distance = 0.0 if insured_addr_str.strip().lower() == checkout_addr_str.strip().lower() else 1.0
            distance_method = 'address_mismatch_proxy'

        sessions_info.append({
            'session_id': cs_nid,
            'session_label': cs_label,
            'session_type': cs_data.get('node_type', cs_data.get('type', 'CareSession')),
            'checkout_address': checkout_addr_str,
            'checkout_lat': checkout_lat,
            'checkout_lon': checkout_lon,
            'checkout_location_node_id': checkout_node_id,
            'distance_from_insured': distance,
            'distance_method': distance_method,
            'session_properties': {k: v for k, v in list(cs_data.get('properties', {}).items())[:10]}
        })

    if not sessions_info:
        return json.dumps({
            'claim_id': claim_id,
            'claim_node_id': claim_nid,
            'insured_node_id': insured_node[0] if insured_node else None,
            'insured_address': insured_addr_str,
            'insured_lat': insured_lat,
            'insured_lon': insured_lon,
            'care_sessions': [],
            'furthest_session': None,
            'note': 'No CareSession nodes found linked to this claim within 2 hops.'
        })

    # Sort by distance descending (None last)
    sessions_with_dist = [s for s in sessions_info if s['distance_from_insured'] is not None]
    sessions_no_dist = [s for s in sessions_info if s['distance_from_insured'] is None]
    sessions_with_dist.sort(key=lambda x: x['distance_from_insured'], reverse=True)
    ranked = sessions_with_dist + sessions_no_dist

    furthest = ranked[0] if ranked else None

    return json.dumps({
        'claim_id': claim_id,
        'claim_node_id': claim_nid,
        'insured_node_id': insured_node[0] if insured_node else None,
        'insured_address': insured_addr_str,
        'insured_lat': insured_lat,
        'insured_lon': insured_lon,
        'furthest_session': furthest,
        'all_sessions_ranked_by_distance': ranked,
        'total_sessions_found': len(sessions_info)
    }, default=str)
