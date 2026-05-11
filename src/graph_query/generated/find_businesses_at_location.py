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

        return run_extension_native("find_businesses_at_location", tool_input)

    G = get_graph()

    location_node_id = tool_input.get('location_node_id', '').strip()
    address_substring = tool_input.get('address_substring', '').strip().lower()
    city = tool_input.get('city', '').strip().lower()
    state = tool_input.get('state', '').strip().lower()

    # Require at least one search criterion
    if not location_node_id and not address_substring and not city and not state:
        return json.dumps({
            'error': 'Provide at least one of: location_node_id, address_substring, city, or state.',
            'businesses_found': []
        })

    # Business-like node types (case-insensitive check)
    business_type_keywords = {'business', 'company', 'employer', 'vendor', 'provider',
                               'organization', 'corporation', 'firm', 'enterprise', 'shop', 'store'}

    def is_business_node(node_id):
        data = G.nodes.get(node_id, {})
        ntype = str(data.get('node_type', data.get('type', ''))).lower()
        label = str(data.get('label', node_id)).lower()
        return any(kw in ntype or kw in label for kw in business_type_keywords)

    def props_match_location(data):
        """Check if any property of a node matches the given location filters."""
        text_fields = []
        for k, v in data.items():
            if any(loc_key in str(k).lower() for loc_key in
                   ('address', 'city', 'state', 'location', 'street', 'zip', 'label', 'name')):
                text_fields.append(str(v).lower())
        combined = ' '.join(text_fields)
        if address_substring and address_substring not in combined:
            return False
        if city and city not in combined:
            return False
        if state and state not in combined:
            return False
        return True

    results = []
    seen = set()

    # Strategy 1: if a location_node_id is given, walk neighbors and find business nodes
    if location_node_id:
        if location_node_id not in G:
            return json.dumps({
                'error': f'Node "{location_node_id}" not found in graph.',
                'businesses_found': []
            })
        neighbors = list(G.successors(location_node_id)) + list(G.predecessors(location_node_id))
        for nbr in neighbors:
            if nbr in seen:
                continue
            seen.add(nbr)
            if is_business_node(nbr):
                data = G.nodes[nbr]
                results.append({
                    'node_id': nbr,
                    'label': data.get('label', nbr),
                    'node_type': data.get('node_type', data.get('type', 'Unknown')),
                    'anchor': 'neighbor_of_location_node',
                    'location_node_id': location_node_id
                })
        # Also check the location node itself if it is business-like
        if location_node_id not in seen and is_business_node(location_node_id):
            data = G.nodes[location_node_id]
            results.append({
                'node_id': location_node_id,
                'label': data.get('label', location_node_id),
                'node_type': data.get('node_type', data.get('type', 'Unknown')),
                'anchor': 'location_node_itself'
            })
            seen.add(location_node_id)

    # Strategy 2: scan all nodes for business types whose properties match location filters
    if address_substring or city or state:
        for node_id, data in G.nodes(data=True):
            if node_id in seen:
                continue
            if is_business_node(node_id) and props_match_location(data):
                seen.add(node_id)
                results.append({
                    'node_id': node_id,
                    'label': data.get('label', node_id),
                    'node_type': data.get('node_type', data.get('type', 'Unknown')),
                    'anchor': 'property_match',
                    'matched_address': data.get('address', data.get('city', data.get('location', '')))
                })

    # Strategy 3: if location_node_id given, also do a property scan on neighbors' neighbors (2-hop)
    # to catch businesses connected via intermediate address/location nodes
    if location_node_id and location_node_id in G:
        direct_neighbors = set(list(G.successors(location_node_id)) + list(G.predecessors(location_node_id)))
        for nbr in direct_neighbors:
            second_hop = list(G.successors(nbr)) + list(G.predecessors(nbr))
            for node_id in second_hop:
                if node_id in seen:
                    continue
                seen.add(node_id)
                if is_business_node(node_id):
                    data = G.nodes[node_id]
                    results.append({
                        'node_id': node_id,
                        'label': data.get('label', node_id),
                        'node_type': data.get('node_type', data.get('type', 'Unknown')),
                        'anchor': '2hop_from_location_node',
                        'via_node': nbr
                    })

    if not results:
        # Provide schema hint so caller can refine query
        node_types = set()
        for _, d in G.nodes(data=True):
            nt = d.get('node_type', d.get('type', ''))
            if nt:
                node_types.add(str(nt))
        return json.dumps({
            'businesses_found': [],
            'count': 0,
            'note': 'No business-like nodes found for the given location criteria.',
            'available_node_types_sample': sorted(node_types)[:30]
        })

    return json.dumps({
        'businesses_found': results,
        'count': len(results)
    })
