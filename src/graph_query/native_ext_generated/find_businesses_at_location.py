"""find_businesses_at_location – Neo4j/Cypher native implementation.

Finds Business-like nodes associated with a given location, specified as a
location node ID, address substring, city, or state.
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BUSINESS_KEYWORDS: list[str] = [
    'business', 'company', 'employer', 'vendor', 'provider',
    'organization', 'corporation', 'firm', 'enterprise', 'shop', 'store',
]

LOCATION_PROP_KEYS: list[str] = [
    'address', 'city', 'state', 'location', 'street', 'zip', 'label', 'name',
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _business_keyword_conditions(node_alias: str) -> str:
    """Return a Cypher boolean expression that is TRUE when node_alias looks
    like a business node (checked against node_type and label)."""
    parts = []
    for kw in BUSINESS_KEYWORDS:
        parts.append(
            f"(toLower(coalesce({node_alias}.node_type,'')) CONTAINS '{kw}'"
            f" OR toLower(coalesce({node_alias}.label,'')) CONTAINS '{kw}')"
        )
    return '(' + '\n        OR '.join(parts) + ')'


def _is_business_node_py(node: dict) -> bool:
    """Python-side guard replicating the same logic for post-filtering."""
    ntype = str(node.get('node_type', node.get('type', ''))).lower()
    label = str(node.get('label', '')).lower()
    return any(kw in ntype or kw in label for kw in BUSINESS_KEYWORDS)


def _props_match_location_py(
    node: dict,
    address_substring: str,
    city: str,
    state: str,
) -> bool:
    """Check node properties for location filter matches (Python side)."""
    text_parts: list[str] = []
    props = parse_properties_json(node.get('properties_json', '{}'))
    # Also include top-level fields
    all_data = {**node, **props}
    for k, v in all_data.items():
        if any(loc_key in str(k).lower() for loc_key in LOCATION_PROP_KEYS):
            text_parts.append(str(v).lower())
    combined = ' '.join(text_parts)
    if address_substring and address_substring not in combined:
        return False
    if city and city not in combined:
        return False
    if state and state not in combined:
        return False
    return True


def _build_location_filter_cypher(
    node_alias: str,
    address_substring: str,
    city: str,
    state: str,
) -> tuple[str, dict]:
    """Build a Cypher WHERE snippet + params for location-text filters.

    Matches against node.label, node.properties_json, and common named
    properties that may carry address/location text.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}

    search_terms: dict[str, str] = {}
    if address_substring:
        search_terms['addr_sub'] = address_substring
    if city:
        search_terms['city_sub'] = city
    if state:
        search_terms['state_sub'] = state

    for param_key, value in search_terms.items():
        # Check label + properties_json blob as a catch-all
        clause = (
            f"(toLower(coalesce({node_alias}.label,'')) CONTAINS ${param_key}"
            f" OR toLower(coalesce({node_alias}.properties_json,'')) CONTAINS ${param_key})"
        )
        clauses.append(clause)
        params[param_key] = value.lower()

    cypher_snippet = ' AND '.join(clauses) if clauses else 'true'
    return cypher_snippet, params


def _node_to_result(record: dict, anchor: str, extra: dict | None = None) -> dict:
    out = {
        'node_id': record.get('node_id', ''),
        'label': record.get('label', record.get('node_id', '')),
        'node_type': record.get('node_type', 'Unknown'),
        'anchor': anchor,
    }
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_native(tool_input: dict[str, Any]) -> str:  # noqa: C901  (complexity OK here)
    location_node_id: str = tool_input.get('location_node_id', '').strip()
    address_substring: str = tool_input.get('address_substring', '').strip().lower()
    city: str = tool_input.get('city', '').strip().lower()
    state: str = tool_input.get('state', '').strip().lower()

    if not location_node_id and not address_substring and not city and not state:
        return json.dumps({
            'error': 'Provide at least one of: location_node_id, address_substring, city, or state.',
            'businesses_found': [],
        })

    business_cond = _business_keyword_conditions('b')
    results: list[dict] = []
    seen: set[str] = set()

    # ------------------------------------------------------------------
    # Strategy 1a: direct neighbours of the location node
    # ------------------------------------------------------------------
    if location_node_id:
        # Verify node exists
        exist_rows = rq(
            'MATCH (n:Entity {node_id: $nid}) RETURN n.node_id AS node_id LIMIT 1',
            {'nid': location_node_id},
        )
        if not exist_rows:
            return json.dumps({
                'error': f'Node "{location_node_id}" not found in graph.',
                'businesses_found': [],
            })

        # Direct neighbours (both directions) that are business-like
        neighbour_rows = rq(
            f"""
            MATCH (loc:Entity {{node_id: $nid}})-[r:GRAPH_EDGE]-(b:Entity)
            WHERE {business_cond}
            RETURN DISTINCT
                b.node_id   AS node_id,
                b.label     AS label,
                b.node_type AS node_type
            LIMIT 200
            """,
            {'nid': location_node_id},
        )
        for row in neighbour_rows:
            nid = row.get('node_id', '')
            if nid and nid not in seen:
                seen.add(nid)
                results.append(_node_to_result(
                    row, 'neighbor_of_location_node',
                    {'location_node_id': location_node_id},
                ))

        # Check whether the location node itself is business-like
        self_rows = rq(
            f"""
            MATCH (b:Entity {{node_id: $nid}})
            WHERE {business_cond}
            RETURN
                b.node_id   AS node_id,
                b.label     AS label,
                b.node_type AS node_type
            LIMIT 1
            """,
            {'nid': location_node_id},
        )
        for row in self_rows:
            nid = row.get('node_id', '')
            if nid and nid not in seen:
                seen.add(nid)
                results.append(_node_to_result(row, 'location_node_itself'))

    # ------------------------------------------------------------------
    # Strategy 2: property-text scan for business nodes matching location
    # ------------------------------------------------------------------
    if address_substring or city or state:
        loc_filter, loc_params = _build_location_filter_cypher(
            'b', address_substring, city, state
        )
        business_cond_b = _business_keyword_conditions('b')
        prop_rows = rq(
            f"""
            MATCH (b:Entity)
            WHERE {business_cond_b}
              AND ({loc_filter})
            RETURN DISTINCT
                b.node_id         AS node_id,
                b.label           AS label,
                b.node_type       AS node_type,
                b.properties_json AS properties_json
            LIMIT 300
            """,
            loc_params,
        )
        for row in prop_rows:
            nid = row.get('node_id', '')
            if not nid or nid in seen:
                continue
            # Python-side fine-grained filter
            if not _props_match_location_py(row, address_substring, city, state):
                continue
            seen.add(nid)
            props = parse_properties_json(row.get('properties_json', '{}'))
            matched_addr = (
                props.get('address')
                or props.get('city')
                or props.get('location')
                or row.get('label', '')
            )
            results.append(_node_to_result(
                row, 'property_match',
                {'matched_address': matched_addr},
            ))

    # ------------------------------------------------------------------
    # Strategy 3: 2-hop from location node
    # ------------------------------------------------------------------
    if location_node_id:
        business_cond_b = _business_keyword_conditions('b')
        two_hop_rows = rq(
            f"""
            MATCH (loc:Entity {{node_id: $nid}})-[:GRAPH_EDGE]-(mid:Entity)-[:GRAPH_EDGE]-(b:Entity)
            WHERE {business_cond_b}
              AND b.node_id <> $nid
            RETURN DISTINCT
                b.node_id   AS node_id,
                b.label     AS label,
                b.node_type AS node_type,
                mid.node_id AS via_node
            LIMIT 300
            """,
            {'nid': location_node_id},
        )
        for row in two_hop_rows:
            nid = row.get('node_id', '')
            if not nid or nid in seen:
                continue
            seen.add(nid)
            results.append(_node_to_result(
                row, '2hop_from_location_node',
                {'via_node': row.get('via_node', '')},
            ))

    # ------------------------------------------------------------------
    # No results → return schema hint
    # ------------------------------------------------------------------
    if not results:
        type_rows = rq(
            """
            MATCH (n:Entity)
            WHERE n.node_type IS NOT NULL
            RETURN DISTINCT n.node_type AS node_type
            LIMIT 50
            """,
            {},
        )
        available_types = sorted(
            {r['node_type'] for r in type_rows if r.get('node_type')}
        )[:30]
        return json.dumps({
            'businesses_found': [],
            'count': 0,
            'note': 'No business-like nodes found for the given location criteria.',
            'available_node_types_sample': available_types,
        })

    return json.dumps({
        'businesses_found': results,
        'count': len(results),
    })