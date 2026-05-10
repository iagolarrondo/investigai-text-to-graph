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

        return run_extension_native("get_claim_provider_service_dates", tool_input)

    graph = get_graph()

    # Locate the claim node by exact id or by label/property substring
    claim_node_id = None
    for node_id, data in graph.nodes(data=True):
        if node_id == tool_input['claim_id']:
            claim_node_id = node_id
            break
        label = data.get('label', '')
        props = data.get('properties', {})
        if tool_input['claim_id'] in str(label) or tool_input['claim_id'] in str(props):
            claim_node_id = node_id
            break

    if claim_node_id is None:
        return json.dumps({'error': f"Claim '{tool_input['claim_id']}' not found in graph.", 'providers': []})

    # Date-related keywords to scan for in property keys
    date_keywords = ['date', 'start', 'end', 'begin', 'from', 'to', 'service', 'period', 'effective', 'termination', 'discharge', 'admission']

    def extract_date_props(props_dict):
        """Return a dict of keys whose name contains a date keyword."""
        result = {}
        if not isinstance(props_dict, dict):
            return result
        for k, v in props_dict.items():
            k_lower = k.lower()
            if any(kw in k_lower for kw in date_keywords):
                result[k] = v
        return result

    provider_type_keywords = ['provider', 'healthcare', 'hospital', 'clinic', 'physician', 'doctor', 'facility', 'practitioner', 'therapist']

    def is_provider_node(ndata):
        ntype = str(ndata.get('node_type', '')).lower()
        nlabel = str(ndata.get('label', '')).lower()
        return any(kw in ntype or kw in nlabel for kw in provider_type_keywords)

    providers_found = []
    visited_pairs = set()

    # Traverse all edges touching the claim node (both directions)
    edges_to_check = []
    for u, v, edata in graph.out_edges(claim_node_id, data=True):
        edges_to_check.append((u, v, edata, 'outgoing'))
    for u, v, edata in graph.in_edges(claim_node_id, data=True):
        edges_to_check.append((u, v, edata, 'incoming'))

    for u, v, edata, direction in edges_to_check:
        # The neighbor is the node that is NOT the claim
        neighbor_id = v if direction == 'outgoing' else u
        if neighbor_id == claim_node_id:
            continue
        if neighbor_id in visited_pairs:
            continue

        neighbor_data = graph.nodes[neighbor_id] if neighbor_id in graph.nodes else {}

        # Check if neighbor is a provider type OR if edge type suggests provider link
        edge_type = str(edata.get('edge_type', edata.get('type', edata.get('label', '')))).lower()
        edge_suggests_provider = any(kw in edge_type for kw in provider_type_keywords + ['treat', 'render', 'service', 'perform', 'assigned', 'billed'])

        if not (is_provider_node(neighbor_data) or edge_suggests_provider):
            continue

        visited_pairs.add(neighbor_id)

        # Gather date props from edge attributes
        edge_dates = extract_date_props(edata)
        # Also check nested 'properties' dict on edge
        edge_prop_dates = extract_date_props(edata.get('properties', {}))
        edge_dates.update(edge_prop_dates)

        # Gather date props from node attributes
        node_dates = extract_date_props(neighbor_data)
        node_prop_dates = extract_date_props(neighbor_data.get('properties', {}))
        node_dates.update(node_prop_dates)

        # Merge all date properties; edge props take precedence
        all_dates = {}
        all_dates.update(node_dates)
        all_dates.update(edge_dates)

        # Try to identify canonical start/end pairs
        start_val = None
        end_val = None
        start_keys = ['service_start_date', 'start_date', 'begin_date', 'service_begin_date', 'from_date', 'effective_date', 'admission_date']
        end_keys = ['service_end_date', 'end_date', 'termination_date', 'service_end', 'to_date', 'discharge_date']

        for sk in start_keys:
            if sk in all_dates:
                start_val = all_dates[sk]
                break
        if start_val is None:
            for k, v in all_dates.items():
                if any(kw in k.lower() for kw in ['start', 'begin', 'from', 'admission', 'effective']):
                    start_val = v
                    break

        for ek in end_keys:
            if ek in all_dates:
                end_val = all_dates[ek]
                break
        if end_val is None:
            for k, v in all_dates.items():
                if any(kw in k.lower() for kw in ['end', 'terminat', 'to_date', 'discharge']):
                    end_val = v
                    break

        providers_found.append({
            'provider_id': neighbor_id,
            'provider_label': neighbor_data.get('label', neighbor_id),
            'provider_type': neighbor_data.get('node_type', 'unknown'),
            'edge_type': edata.get('edge_type', edata.get('type', edata.get('label', 'unknown'))),
            'service_start': start_val,
            'service_end': end_val,
            'all_date_properties': all_dates if all_dates else None
        })

    if not providers_found:
        return json.dumps({
            'claim_id': claim_node_id,
            'message': 'No provider nodes or service date properties found for this claim.',
            'providers': []
        })

    return json.dumps({
        'claim_id': claim_node_id,
        'provider_count': len(providers_found),
        'providers': providers_found
    })
