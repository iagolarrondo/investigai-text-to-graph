"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
    G = get_graph()
    min_accounts = tool_input.get('min_accounts_per_group', 2)

    # Identify BankAccount nodes
    bank_account_nodes = [
        n for n, d in G.nodes(data=True)
        if str(d.get('node_type', '')).lower() in ('bankaccount', 'bank_account')
        or str(d.get('label', '')).lower() in ('bankaccount', 'bank_account')
    ]

    if not bank_account_nodes:
        return json.dumps({'result': 'no_bank_account_nodes_found', 'groups': []})

    # Customer-like and provider-like node type sets
    customer_types = {'person', 'customer', 'insured', 'policyholder'}
    provider_types = {'healthcareprovider', 'healthcare_provider', 'provider', 'medicalprovider', 'medical_provider'}

    def classify_neighbor(node_id):
        d = G.nodes[node_id]
        nt = str(d.get('node_type', '')).lower().replace(' ', '').replace('_', '')
        lbl = str(d.get('label', '')).lower().replace(' ', '').replace('_', '')
        combined = nt + '|' + lbl
        is_customer = any(ct.replace('_', '') in combined for ct in customer_types)
        is_provider = any(pt.replace('_', '') in combined for pt in provider_types)
        return is_customer, is_provider

    # For each bank account, collect linked customers and providers
    ba_customers = {}  # bank_account_id -> set of customer node ids
    ba_providers = {}  # bank_account_id -> set of provider node ids

    for ba in bank_account_nodes:
        customers = set()
        providers = set()
        neighbors = list(G.successors(ba)) + list(G.predecessors(ba))
        for nb in neighbors:
            if nb == ba:
                continue
            is_cust, is_prov = classify_neighbor(nb)
            if is_cust:
                customers.add(nb)
            if is_prov:
                providers.add(nb)
        ba_customers[ba] = customers
        ba_providers[ba] = providers

    # Group bank accounts by (customer_id, provider_id) pairs
    from collections import defaultdict
    pair_to_accounts = defaultdict(list)

    for ba in bank_account_nodes:
        for cust in ba_customers[ba]:
            for prov in ba_providers[ba]:
                pair_to_accounts[(cust, prov)].append(ba)

    # Filter groups by minimum account count
    results = []
    for (cust_id, prov_id), accounts in pair_to_accounts.items():
        unique_accounts = list(set(accounts))
        if len(unique_accounts) >= min_accounts:
            cust_data = G.nodes[cust_id]
            prov_data = G.nodes[prov_id]
            results.append({
                'customer_id': cust_id,
                'customer_label': cust_data.get('label', cust_data.get('name', cust_id)),
                'customer_type': cust_data.get('node_type', ''),
                'provider_id': prov_id,
                'provider_label': prov_data.get('label', prov_data.get('name', prov_id)),
                'provider_type': prov_data.get('node_type', ''),
                'bank_account_ids': unique_accounts,
                'account_count': len(unique_accounts)
            })

    results.sort(key=lambda x: -x['account_count'])

    if not results:
        # Also report summary for debugging
        has_any_link = sum(1 for ba in bank_account_nodes if ba_customers[ba] or ba_providers[ba])
        has_both = sum(1 for ba in bank_account_nodes if ba_customers[ba] and ba_providers[ba])
        return json.dumps({
            'result': 'no_groups_found',
            'total_bank_accounts_scanned': len(bank_account_nodes),
            'accounts_with_any_link': has_any_link,
            'accounts_with_both_customer_and_provider': has_both,
            'note': 'No bank accounts share both a common customer and a common healthcare provider at the requested minimum group size.',
            'groups': []
        })

    return json.dumps({
        'result': 'groups_found',
        'total_groups': len(results),
        'total_bank_accounts_scanned': len(bank_account_nodes),
        'min_accounts_per_group': min_accounts,
        'groups': results
    })
