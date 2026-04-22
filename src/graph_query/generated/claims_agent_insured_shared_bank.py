"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
    G = get_graph()
    limit = int(tool_input.get("limit", 200))

    # Step 1: Build bank account membership index
    # bank_account_id -> set of person_ids
    bank_to_people = {}
    # person_id -> set of bank_account_ids
    person_to_banks = {}

    for node_id, node_data in G.nodes(data=True):
        ntype = node_data.get("node_type", node_data.get("type", ""))
        if ntype in ("BankAccount", "Bank_Account", "bank_account"):
            bank_to_people[node_id] = set()

    # Traverse edges to find person<->bank_account relationships
    bank_edge_types = {
        "HAS_BANK_ACCOUNT", "HOLDS_BANK_ACCOUNT", "SHARES_BANK_ACCOUNT",
        "OWNS_BANK_ACCOUNT", "BANK_ACCOUNT", "has_bank_account",
        "holds_bank_account", "shares_bank_account"
    }

    for u, v, edge_data in G.edges(data=True):
        etype = edge_data.get("edge_type", edge_data.get("type", ""))
        u_type = G.nodes[u].get("node_type", G.nodes[u].get("type", ""))
        v_type = G.nodes[v].get("node_type", G.nodes[v].get("type", ""))

        person_node = None
        bank_node = None

        if etype in bank_edge_types or "bank" in etype.lower():
            if "Person" in u_type:
                person_node = u
                bank_node = v
            elif "Person" in v_type:
                person_node = v
                bank_node = u
        else:
            # Also detect by node types regardless of edge label
            if "Person" in u_type and "Bank" in v_type:
                person_node = u
                bank_node = v
            elif "Person" in v_type and "Bank" in u_type:
                person_node = v
                bank_node = u

        if person_node and bank_node and bank_node in bank_to_people:
            bank_to_people[bank_node].add(person_node)
            person_to_banks.setdefault(person_node, set()).add(bank_node)

    # Step 2: Enumerate all Claims
    claim_nodes = [
        nid for nid, nd in G.nodes(data=True)
        if nd.get("node_type", nd.get("type", "")) in ("Claim", "claim")
    ]

    results = []

    for claim_id in claim_nodes:
        if len(results) >= limit:
            break

        # Step 3: Find the policy for this claim
        policy_id = None
        for nbr in list(G.successors(claim_id)) + list(G.predecessors(claim_id)):
            nbr_type = G.nodes[nbr].get("node_type", G.nodes[nbr].get("type", ""))
            if "Policy" in nbr_type or "policy" in nbr_type.lower():
                policy_id = nbr
                break

        if not policy_id:
            continue

        # Step 4: Find the writing agent (SOLD_POLICY edge) and insureds (IS_COVERED_BY)
        agent_ids = set()
        insured_ids = set()

        for u, v, ed in G.edges(policy_id, data=True):
            etype = ed.get("edge_type", ed.get("type", ""))
            v_type = G.nodes[v].get("node_type", G.nodes[v].get("type", ""))
            if etype in ("SOLD_POLICY", "sold_policy", "WRITING_AGENT", "writing_agent") and "Person" in v_type:
                agent_ids.add(v)
            elif etype in ("IS_COVERED_BY", "is_covered_by", "COVERED_BY", "covered_by") and "Person" in v_type:
                insured_ids.add(v)

        for u, v, ed in G.in_edges(policy_id, data=True):
            etype = ed.get("edge_type", ed.get("type", ""))
            u_type = G.nodes[u].get("node_type", G.nodes[u].get("type", ""))
            if etype in ("SOLD_POLICY", "sold_policy", "WRITING_AGENT", "writing_agent") and "Person" in u_type:
                agent_ids.add(u)
            elif etype in ("IS_COVERED_BY", "is_covered_by", "COVERED_BY", "covered_by") and "Person" in u_type:
                insured_ids.add(u)

        if not agent_ids or not insured_ids:
            continue

        # Step 5: For each agent, find their bank accounts, then check if any insured shares one
        for agent_id in agent_ids:
            agent_banks = person_to_banks.get(agent_id, set())
            if not agent_banks:
                continue

            for insured_id in insured_ids:
                if insured_id == agent_id:
                    continue
                insured_banks = person_to_banks.get(insured_id, set())
                shared_banks = agent_banks & insured_banks
                for bank_id in shared_banks:
                    agent_label = G.nodes[agent_id].get("label", G.nodes[agent_id].get("name", agent_id))
                    insured_label = G.nodes[insured_id].get("label", G.nodes[insured_id].get("name", insured_id))
                    results.append({
                        "claim_id": claim_id,
                        "policy_id": policy_id,
                        "agent_id": agent_id,
                        "agent_name": agent_label,
                        "insured_id": insured_id,
                        "insured_name": insured_label,
                        "bank_account_id": bank_id
                    })
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

    return json.dumps({
        "match_count": len(results),
        "truncated": len(results) >= limit,
        "matches": results
    }, default=str)
