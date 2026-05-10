"""get_claim_provider_service_dates – Neo4j/Cypher native implementation.

Given a claim_id, traverses edges from the Claim node to any provider-like
nodes (both directions) and returns each provider's id, label, type, edge_type,
and any service start/end date properties found on those edges or provider nodes.
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATE_KEYWORDS = [
    'date', 'start', 'end', 'begin', 'from', 'to',
    'service', 'period', 'effective', 'termination',
    'discharge', 'admission',
]

PROVIDER_KEYWORDS = [
    'provider', 'healthcare', 'hospital', 'clinic',
    'physician', 'doctor', 'facility', 'practitioner', 'therapist',
]

EDGE_PROVIDER_KEYWORDS = PROVIDER_KEYWORDS + [
    'treat', 'render', 'service', 'perform', 'assigned', 'billed',
]

START_KEY_PRIORITY = [
    'service_start_date', 'start_date', 'begin_date',
    'service_begin_date', 'from_date', 'effective_date', 'admission_date',
]
END_KEY_PRIORITY = [
    'service_end_date', 'end_date', 'termination_date',
    'service_end', 'to_date', 'discharge_date',
]
START_FALLBACK_KWS = ['start', 'begin', 'from', 'admission', 'effective']
END_FALLBACK_KWS   = ['end', 'terminat', 'to_date', 'discharge']


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_date_props(props: dict) -> dict:
    """Return a sub-dict whose keys contain at least one DATE_KEYWORD."""
    if not isinstance(props, dict):
        return {}
    return {
        k: v
        for k, v in props.items()
        if any(kw in k.lower() for kw in DATE_KEYWORDS)
    }


def _is_provider(node_type: str, label: str) -> bool:
    nt = node_type.lower()
    lb = label.lower()
    return any(kw in nt or kw in lb for kw in PROVIDER_KEYWORDS)


def _edge_suggests_provider(edge_type: str) -> bool:
    et = edge_type.lower()
    return any(kw in et for kw in EDGE_PROVIDER_KEYWORDS)


def _pick_start_end(all_dates: dict) -> tuple[Any, Any]:
    """Derive canonical start/end values from a merged date-property dict."""
    start_val = None
    for sk in START_KEY_PRIORITY:
        if sk in all_dates:
            start_val = all_dates[sk]
            break
    if start_val is None:
        for k, v in all_dates.items():
            if any(kw in k.lower() for kw in START_FALLBACK_KWS):
                start_val = v
                break

    end_val = None
    for ek in END_KEY_PRIORITY:
        if ek in all_dates:
            end_val = all_dates[ek]
            break
    if end_val is None:
        for k, v in all_dates.items():
            if any(kw in k.lower() for kw in END_FALLBACK_KWS):
                end_val = v
                break

    return start_val, end_val


def _safe_parse(raw) -> dict:
    """Parse a properties_json field safely, returning a plain dict."""
    if not raw:
        return {}
    try:
        result = parse_properties_json(raw)
        return result if isinstance(result, dict) else {}
    except Exception:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_native(tool_input: dict[str, Any]) -> str:
    """Return provider service-date information for a given claim."""

    claim_id: str = tool_input.get('claim_id', '').strip()
    if not claim_id:
        return json.dumps({'error': 'claim_id is required.', 'providers': []})

    # ------------------------------------------------------------------
    # Step 1: Locate the claim node
    # ------------------------------------------------------------------
    locate_query = """
        MATCH (c:Entity)
        WHERE c.node_id = $claim_id
           OR c.label   = $claim_id
           OR c.node_id CONTAINS $claim_id
           OR c.label   CONTAINS $claim_id
        RETURN c.node_id          AS node_id,
               c.label            AS label,
               c.node_type        AS node_type,
               c.properties_json  AS properties_json
        LIMIT 1
    """
    locate_rows = rq(locate_query, {'claim_id': claim_id})

    if not locate_rows:
        return json.dumps({
            'error': f"Claim '{claim_id}' not found in graph.",
            'providers': [],
        })

    claim_row   = locate_rows[0]
    claim_node_id = claim_row['node_id']

    # ------------------------------------------------------------------
    # Step 2: Fetch all neighbouring edges/nodes (both directions)
    # ------------------------------------------------------------------
    neighbour_query = """
        MATCH (c:Entity {node_id: $claim_node_id})

        // Outgoing edges
        OPTIONAL MATCH (c)-[r_out:GRAPH_EDGE]->(nb_out:Entity)

        // Incoming edges
        OPTIONAL MATCH (nb_in:Entity)-[r_in:GRAPH_EDGE]->(c)

        WITH
            collect(DISTINCT {
                neighbor_id:         nb_out.node_id,
                neighbor_label:      nb_out.label,
                neighbor_type:       nb_out.node_type,
                neighbor_props_json: nb_out.properties_json,
                edge_type:           r_out.edge_type,
                edge_props_json:     r_out.properties_json,
                direction:           'outgoing'
            }) AS out_rows,
            collect(DISTINCT {
                neighbor_id:         nb_in.node_id,
                neighbor_label:      nb_in.label,
                neighbor_type:       nb_in.node_type,
                neighbor_props_json: nb_in.properties_json,
                edge_type:           r_in.edge_type,
                edge_props_json:     r_in.properties_json,
                direction:           'incoming'
            }) AS in_rows

        WITH out_rows + in_rows AS all_rows
        UNWIND all_rows AS row
        RETURN row
        LIMIT 500
    """
    rows = rq(neighbour_query, {'claim_node_id': claim_node_id})

    # ------------------------------------------------------------------
    # Step 3: Filter and enrich
    # ------------------------------------------------------------------
    providers_found = []
    visited_ids: set[str] = set()

    for record in rows:
        row = record.get('row', record)  # handle both dict-of-row and raw
        if isinstance(record, dict) and 'row' not in record:
            row = record

        neighbor_id    = row.get('neighbor_id')
        neighbor_label = row.get('neighbor_label') or ''
        neighbor_type  = row.get('neighbor_type')  or ''
        edge_type_raw  = row.get('edge_type')       or ''

        if not neighbor_id or neighbor_id == claim_node_id:
            continue
        if neighbor_id in visited_ids:
            continue

        # Determine if this neighbour qualifies as a provider
        provider_node = _is_provider(neighbor_type, neighbor_label)
        edge_provider = _edge_suggests_provider(edge_type_raw)

        if not (provider_node or edge_provider):
            continue

        visited_ids.add(neighbor_id)

        # Parse properties_json blobs
        node_props = _safe_parse(row.get('neighbor_props_json'))
        edge_props = _safe_parse(row.get('edge_props_json'))

        # Extract date-related keys
        node_dates = _extract_date_props(node_props)
        edge_dates = _extract_date_props(edge_props)

        # Merge: edge properties take precedence
        all_dates: dict = {}
        all_dates.update(node_dates)
        all_dates.update(edge_dates)

        start_val, end_val = _pick_start_end(all_dates)

        providers_found.append({
            'provider_id':         neighbor_id,
            'provider_label':      neighbor_label or neighbor_id,
            'provider_type':       neighbor_type  or 'unknown',
            'edge_type':           edge_type_raw  or 'unknown',
            'service_start':       start_val,
            'service_end':         end_val,
            'all_date_properties': all_dates if all_dates else None,
        })

    # ------------------------------------------------------------------
    # Step 4: Return
    # ------------------------------------------------------------------
    if not providers_found:
        return json.dumps({
            'claim_id': claim_node_id,
            'message':  'No provider nodes or service date properties found for this claim.',
            'providers': [],
        })

    return json.dumps({
        'claim_id':       claim_node_id,
        'provider_count': len(providers_found),
        'providers':      providers_found,
    })