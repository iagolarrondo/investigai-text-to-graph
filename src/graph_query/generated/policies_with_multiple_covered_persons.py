"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
    G = get_graph()
    min_persons = int(tool_input.get('min_persons', 2))

    # Edge types linking a person to a policy
    coverage_edge_types = {'IS_COVERED_BY', 'SOLD_POLICY'}

    # Collect persons per policy by scanning edges from Person -> Policy
    policy_persons = {}

    for u, v, data in G.edges(data=True):
        etype = data.get('edge_type', data.get('label', ''))
        if etype not in coverage_edge_types:
            continue
        # Determine which node is the policy and which is the person
        u_type = G.nodes[u].get('node_type', G.nodes[u].get('label', ''))
        v_type = G.nodes[v].get('node_type', G.nodes[v].get('label', ''))

        policy_id = None
        person_id = None

        if u_type == 'Policy' and v_type == 'Person':
            policy_id, person_id = u, v
        elif v_type == 'Policy' and u_type == 'Person':
            policy_id, person_id = v, u
        elif u_type == 'Policy':
            policy_id = u
        elif v_type == 'Policy':
            policy_id = v

        if policy_id is None:
            continue

        if policy_id not in policy_persons:
            policy_persons[policy_id] = set()
        if person_id:
            policy_persons[policy_id].add(person_id)

    # Filter policies meeting the threshold
    results = []
    for policy_id, persons in policy_persons.items():
        count = len(persons)
        if count >= min_persons:
            node_data = G.nodes.get(policy_id, {})
            policy_label = node_data.get('name', node_data.get('policy_number', node_data.get('label', policy_id)))
            results.append({
                'policy_id': policy_id,
                'policy_label': policy_label,
                'covered_person_count': count,
                'covered_person_ids': sorted(persons)
            })

    results.sort(key=lambda x: x['covered_person_count'], reverse=True)

    if not results:
        return json.dumps({
            'policies_with_multiple_covered_persons': [],
            'count': 0,
            'message': f'No policies found with {min_persons} or more covered persons.'
        })

    return json.dumps({
        'policies_with_multiple_covered_persons': results,
        'count': len(results),
        'min_persons_filter': min_persons
    })
