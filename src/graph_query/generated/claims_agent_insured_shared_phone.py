"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
    G = get_graph()

    def extract_phones(node_data):
        """Return a set of normalized phone strings from a node's properties."""
        phones = set()
        phone_keys = [k for k in node_data.keys() if 'phone' in k.lower()]
        for k in phone_keys:
            val = node_data.get(k)
            if val and isinstance(val, str):
                # Normalize: keep digits only for comparison
                digits = ''.join(c for c in val if c.isdigit())
                if len(digits) >= 7:
                    phones.add(digits)
        return phones

    matches = []

    # Iterate over all Claim nodes
    claim_nodes = [
        n for n, d in G.nodes(data=True)
        if d.get('node_type', '') == 'Claim'
    ]

    for claim_id in claim_nodes:
        # Find policy linked to this claim via IS_CLAIM_AGAINST_POLICY (claim -> policy)
        policy_ids = []
        for successor in G.successors(claim_id):
            edge_data = G.edges[claim_id, successor]
            etype = edge_data.get('edge_type', '')
            ntype = G.nodes[successor].get('node_type', '')
            if ntype == 'Policy' and 'CLAIM' in etype.upper():
                policy_ids.append(successor)
        # Also check predecessors in case edge direction is reversed
        if not policy_ids:
            for predecessor in G.predecessors(claim_id):
                edge_data = G.edges[predecessor, claim_id]
                etype = edge_data.get('edge_type', '')
                ntype = G.nodes[predecessor].get('node_type', '')
                if ntype == 'Policy' and 'CLAIM' in etype.upper():
                    policy_ids.append(predecessor)

        for policy_id in policy_ids:
            agent_ids = []
            insured_ids = []

            # From policy, find agents (SOLD_POLICY) and insureds (IS_COVERED_BY)
            # Check successors of policy
            for nbr in G.successors(policy_id):
                edge_data = G.edges[policy_id, nbr]
                etype = edge_data.get('edge_type', '')
                ntype = G.nodes[nbr].get('node_type', '')
                if ntype == 'Person':
                    if 'SOLD' in etype.upper():
                        agent_ids.append(nbr)
                    elif 'COVERED' in etype.upper():
                        insured_ids.append(nbr)

            # Check predecessors of policy
            for nbr in G.predecessors(policy_id):
                edge_data = G.edges[nbr, policy_id]
                etype = edge_data.get('edge_type', '')
                ntype = G.nodes[nbr].get('node_type', '')
                if ntype == 'Person':
                    if 'SOLD' in etype.upper():
                        agent_ids.append(nbr)
                    elif 'COVERED' in etype.upper():
                        insured_ids.append(nbr)

            # Deduplicate
            agent_ids = list(set(agent_ids))
            insured_ids = list(set(insured_ids))

            for agent_id in agent_ids:
                agent_data = G.nodes[agent_id]
                agent_phones = extract_phones(agent_data)
                if not agent_phones:
                    continue

                for insured_id in insured_ids:
                    if insured_id == agent_id:
                        continue
                    insured_data = G.nodes[insured_id]
                    insured_phones = extract_phones(insured_data)

                    shared = agent_phones & insured_phones
                    for phone in shared:
                        matches.append({
                            'claim_id': claim_id,
                            'policy_id': policy_id,
                            'agent_id': agent_id,
                            'insured_id': insured_id,
                            'shared_phone': phone
                        })

    if not matches:
        return json.dumps({
            'result': 'no_matches',
            'message': 'No insureds share a phone number with the writing agent of any claim policy.',
            'claims_checked': len(claim_nodes)
        })

    return json.dumps({
        'match_count': len(matches),
        'claims_checked': len(claim_nodes),
        'matches': matches
    })
