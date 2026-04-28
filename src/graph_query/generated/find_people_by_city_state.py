"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
    city = tool_input.get("city", "").strip().upper()
    state = tool_input.get("state", "").strip().upper()

    if not city:
        return json.dumps({"error": "city is required"})

    G = get_graph()

    # Step 1: Find candidate nodes whose label or properties mention the city (and optionally state)
    candidate_address_nodes = []
    for node_id, data in G.nodes(data=True):
        label = str(data.get("label", "")).upper()
        # Build a combined string of all property values for matching
        all_values = " ".join(str(v).upper() for v in data.values())

        city_match = city in label or city in all_values
        state_match = (not state) or (state in label or state in all_values)

        if city_match and state_match:
            candidate_address_nodes.append((node_id, data))

    # Step 2: From each candidate node, collect directly linked Person nodes
    # Also check if the candidate itself is a Person
    person_map = {}  # person_node_id -> {label, address_context}

    def collect_person(pid, pdata, context_label):
        if pid not in person_map:
            person_map[pid] = {
                "person_id": pid,
                "label": pdata.get("label", pid),
                "address_context": []
            }
        person_map[pid]["address_context"].append(context_label)

    for node_id, data in candidate_address_nodes:
        node_type = str(data.get("node_type", "")).lower()
        node_label = data.get("label", node_id)
        context = str(node_label)

        # If the candidate itself is a Person
        if node_type == "person" or node_type == "":
            ndata = G.nodes[node_id]
            if str(ndata.get("node_type", "")).lower() in ("person", ""):
                # Check all neighbors to see if this really is a person
                pass
            if str(data.get("node_type", "")).lower() == "person":
                collect_person(node_id, data, f"self:{context}")
                continue

        # Check neighbors (both directions) for Person nodes
        neighbors = list(G.successors(node_id)) + list(G.predecessors(node_id))
        for nbr in neighbors:
            nbr_data = G.nodes[nbr]
            if str(nbr_data.get("node_type", "")).lower() == "person":
                collect_person(nbr, nbr_data, context)

    # Step 3: Also scan all Person nodes directly for city/state in their own properties
    for node_id, data in G.nodes(data=True):
        if str(data.get("node_type", "")).lower() == "person":
            all_values = " ".join(str(v).upper() for v in data.values())
            city_match = city in all_values
            state_match = (not state) or (state in all_values)
            if city_match and state_match:
                if node_id not in person_map:
                    person_map[node_id] = {
                        "person_id": node_id,
                        "label": data.get("label", node_id),
                        "address_context": ["direct_property_match"]
                    }

    if not person_map:
        query_desc = city + (f", {state}" if state else "")
        return json.dumps({
            "city": city,
            "state": state,
            "people_found": 0,
            "people": [],
            "note": f"No Person nodes found associated with {query_desc}"
        })

    results = list(person_map.values())
    # Deduplicate address_context entries
    for r in results:
        r["address_context"] = list(dict.fromkeys(r["address_context"]))

    return json.dumps({
        "city": city,
        "state": state,
        "people_found": len(results),
        "people": results
    })
