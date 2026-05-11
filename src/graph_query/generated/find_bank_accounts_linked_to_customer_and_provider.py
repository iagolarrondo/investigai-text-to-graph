"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
    G = get_graph()

    # Resolve which node types count as 'customer' and 'provider'
    customer_types = set(tool_input.get('customer_node_types') or ['Person', 'Customer', 'Insured'])
    provider_types = set(tool_input.get('provider_node_types') or ['HealthcareProvider', 'Provider', 'Healthcare Provider'])

    # Collect all node types present in the graph (case-insensitive fallback)
    all_node_types = set()
    for nid, data in G.nodes(data=True):
        nt = data.get('node_type', data.get('type', ''))
        all_node_types.add(nt)

    # Build case-insensitive expanded sets if exact types not found
    def expand_types(requested_set, available_set):
        matched = set()
        for req in requested_set:
            req_lower = req.lower().replace(' ', '')
            for avail in available_set:
                if avail.lower().replace(' ', '') == req_lower:
                    matched.add(avail)
        # If nothing matched, fall back to substring match
        if not matched:
            for req in requested_set:
                req_lower = req.lower().replace(' ', '')
                for avail in available_set:
                    if req_lower in avail.lower().replace(' ', '') or avail.lower().replace(' ', '') in req_lower:
                        matched.add(avail)
        return matched

    resolved_customer_types = expand_types(customer_types, all_node_types)
    resolved_provider_types = expand_types(provider_types, all_node_types)

    # Identify BankAccount nodes
    bank_account_ids = []
    for nid, data in G.nodes(data=True):
        nt = data.get('node_type', data.get('type', ''))
        if 'bank' in nt.lower() or 'account' in nt.lower():
            bank_account_ids.append(nid)

    if not bank_account_ids:
        return json.dumps({
            'status': 'no_bank_accounts_found',
            'message': 'No BankAccount nodes detected in the graph.',
            'node_types_seen': sorted(all_node_types)
        })

    results = []

    for ba_id in bank_account_ids:
        # Collect all neighbors (both directions) for this bank account
        neighbors = list(G.successors(ba_id)) + list(G.predecessors(ba_id))

        linked_customers = []
        linked_providers = []

        for nbr in neighbors:
            nbr_data = G.nodes[nbr]
            nbr_type = nbr_data.get('node_type', nbr_data.get('type', ''))
            if nbr_type in resolved_customer_types:
                linked_customers.append(nbr)
            elif nbr_type in resolved_provider_types:
                linked_providers.append(nbr)

        if linked_customers and linked_providers:
            ba_data = G.nodes[ba_id]
            results.append({
                'bank_account_id': ba_id,
                'bank_account_label': ba_data.get('label', ba_id),
                'linked_customer_ids': linked_customers,
                'linked_provider_ids': linked_providers,
                'customer_count': len(linked_customers),
                'provider_count': len(linked_providers)
            })

    summary = {
        'status': 'ok',
        'bank_accounts_checked': len(bank_account_ids),
        'matches_found': len(results),
        'resolved_customer_types': sorted(resolved_customer_types),
        'resolved_provider_types': sorted(resolved_provider_types),
        'matches': results
    }

    if not results:
        summary['message'] = (
            'No BankAccount nodes found with simultaneous links to both a customer/person '
            'and a healthcare provider. This may indicate the graph does not contain this '
            'overlap pattern, or the node types differ from expected.'
        )
        summary['all_node_types_in_graph'] = sorted(all_node_types)

    return json.dumps(summary)
