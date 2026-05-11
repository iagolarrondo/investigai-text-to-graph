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

        return run_extension_native("get_claim_icp_policyholder_address_comparison", tool_input)

    graph = get_graph()

    # --- locate the claim node ---
    claim_node_id = None
    for nid, data in graph.nodes(data=True):
        label = str(data.get('label', ''))
        ntype = str(data.get('node_type', data.get('type', '')))
        if label == tool_input['claim_id'] or nid == tool_input['claim_id']:
            claim_node_id = nid
            break
        if tool_input['claim_id'].upper() in label.upper() and 'claim' in ntype.lower():
            claim_node_id = nid
            break

    if claim_node_id is None:
        return json.dumps({'error': f"Claim '{tool_input['claim_id']}' not found in graph."})

    def node_type(nid):
        d = graph.nodes[nid]
        return str(d.get('node_type', d.get('type', ''))).lower()

    def node_label(nid):
        return str(graph.nodes[nid].get('label', nid))

    def address_props(nid):
        """Return a dict of address-related properties from a node."""
        d = graph.nodes[nid]
        keys = ['address', 'home_address', 'street', 'street_address',
                'city', 'state', 'zip', 'zip_code', 'postal_code', 'full_address']
        return {k: v for k, v in d.items() if k.lower() in keys or 'address' in k.lower()}

    def find_address_neighbors(nid):
        """Return address properties: first from Address-type neighbors, else from node itself."""
        addr_data = {}
        addr_node_ids = []
        for successor in graph.successors(nid):
            if 'address' in node_type(successor):
                addr_node_ids.append(successor)
        for predecessor in graph.predecessors(nid):
            if 'address' in node_type(predecessor):
                addr_node_ids.append(predecessor)
        for addr_nid in addr_node_ids:
            d = graph.nodes[addr_nid]
            for k, v in d.items():
                if k not in ('node_type', 'type', 'id'):
                    addr_data[k] = v
        if not addr_data:
            addr_data = address_props(nid)
        return addr_data

    # --- find ICP node(s) linked to the claim ---
    icp_nodes = []
    for successor in graph.successors(claim_node_id):
        nt = node_type(successor)
        if 'icp' in nt or 'independentcare' in nt or 'independent_care' in nt or 'careprovider' in nt:
            icp_nodes.append(successor)
    for predecessor in graph.predecessors(claim_node_id):
        nt = node_type(predecessor)
        if 'icp' in nt or 'independentcare' in nt or 'independent_care' in nt or 'careprovider' in nt:
            if predecessor not in icp_nodes:
                icp_nodes.append(predecessor)

    # --- find Policy node linked to the claim ---
    policy_node_id = None
    for successor in graph.successors(claim_node_id):
        if 'policy' in node_type(successor):
            policy_node_id = successor
            break
    if policy_node_id is None:
        for predecessor in graph.predecessors(claim_node_id):
            if 'policy' in node_type(predecessor):
                policy_node_id = predecessor
                break

    # --- find Policyholder / insured Person from the policy ---
    policyholder_node_id = None
    policyholder_role = None
    if policy_node_id is not None:
        for neighbor in list(graph.predecessors(policy_node_id)) + list(graph.successors(policy_node_id)):
            nt = node_type(neighbor)
            if 'person' in nt or 'insured' in nt or 'customer' in nt:
                edge_data_fwd = graph.get_edge_data(neighbor, policy_node_id) or {}
                edge_data_rev = graph.get_edge_data(policy_node_id, neighbor) or {}
                rel = str(edge_data_fwd.get('edge_type', edge_data_fwd.get('type',
                          edge_data_rev.get('edge_type', edge_data_rev.get('type', ''))))).lower()
                if 'covered' in rel or 'holder' in rel or 'insured' in rel or 'owner' in rel or rel == '':
                    policyholder_node_id = neighbor
                    policyholder_role = rel or 'unknown'
                    break

    # --- build result ---
    result = {
        'claim_id': tool_input['claim_id'],
        'claim_node_id': claim_node_id,
        'icp_count': len(icp_nodes),
        'icps': [],
        'policyholder': None,
        'shared_address': False,
        'notes': []
    }

    if policy_node_id is None:
        result['notes'].append('No Policy node found linked to this claim.')
    if not icp_nodes:
        result['notes'].append('No ICP node found linked to this claim.')

    # Policyholder address
    ph_addr = {}
    if policyholder_node_id:
        ph_addr = find_address_neighbors(policyholder_node_id)
        result['policyholder'] = {
            'node_id': policyholder_node_id,
            'label': node_label(policyholder_node_id),
            'role': policyholder_role,
            'address': ph_addr
        }
    else:
        result['notes'].append('No Policyholder/Insured Person found on the policy.')

    def normalize_addr(addr_dict):
        """Produce a lowercased, stripped, sorted-key string for comparison."""
        if not addr_dict:
            return ''
        parts = []
        for k in sorted(addr_dict.keys()):
            v = str(addr_dict[k]).strip().lower()
            if v:
                parts.append(v)
        return '|'.join(parts)

    ph_norm = normalize_addr(ph_addr)

    any_shared = False
    for icp_nid in icp_nodes:
        icp_addr = find_address_neighbors(icp_nid)
        icp_norm = normalize_addr(icp_addr)
        shared = False
        if ph_norm and icp_norm and ph_norm == icp_norm:
            shared = True
            any_shared = True
        elif ph_addr and icp_addr:
            # partial match: check if full_address or address fields overlap
            for key in ('address', 'full_address', 'home_address', 'street_address'):
                ph_val = str(ph_addr.get(key, '')).strip().lower()
                icp_val = str(icp_addr.get(key, '')).strip().lower()
                if ph_val and icp_val and ph_val == icp_val:
                    shared = True
                    any_shared = True
                    break
        result['icps'].append({
            'node_id': icp_nid,
            'label': node_label(icp_nid),
            'address': icp_addr,
            'shared_address_with_policyholder': shared
        })

    result['shared_address'] = any_shared

    if not ph_addr and policyholder_node_id:
        result['notes'].append('Policyholder address properties not found in graph.')
    if icp_nodes and all(not icp['address'] for icp in result['icps']):
        result['notes'].append('ICP address properties not found in graph.')

    return json.dumps(result)
