"""get_care_sessions_exceeding_distance_threshold – Neo4j/Cypher native implementation.

Finds CareSession nodes linked to a claim, computes haversine distance from the
insured's address coordinates, and returns sessions exceeding a distance threshold.
"""
from __future__ import annotations

import json
import math
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_latlon(props: dict) -> tuple[float | None, float | None]:
    """Return (lat, lon) extracted from a properties dict, or (None, None)."""
    lat: float | None = None
    lon: float | None = None
    for k, v in props.items():
        kl = k.lower()
        if v is None:
            continue
        if ('lat' in kl) and ('lon' not in kl) and ('lng' not in kl):
            try:
                lat = float(v)
            except (TypeError, ValueError):
                pass
        elif 'lon' in kl or 'lng' in kl:
            try:
                lon = float(v)
            except (TypeError, ValueError):
                pass
    return lat, lon


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two lat/lon points."""
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse(node: dict) -> dict:
    """Merge base node fields with parsed properties_json."""
    base = dict(node)
    pj = base.pop('properties_json', None) or '{}'
    try:
        extra = parse_properties_json(pj) if callable(parse_properties_json) else json.loads(pj)
    except Exception:
        try:
            extra = json.loads(pj)
        except Exception:
            extra = {}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_native(tool_input: dict[str, Any]) -> str:
    claim_id = (tool_input.get('claim_id') or '').strip()
    threshold = float(tool_input.get('distance_threshold_miles', 5.0))

    if not claim_id:
        return json.dumps({'error': 'claim_id is required'})

    # ------------------------------------------------------------------
    # 1. Locate the Claim node
    # ------------------------------------------------------------------
    claim_rows = rq(
        """
        MATCH (c:Entity)
        WHERE c.node_id = $cid
           OR c.label   = $cid
           OR c.properties_json CONTAINS $cid
        RETURN c.node_id       AS node_id,
               c.node_type     AS node_type,
               c.label         AS label,
               c.properties_json AS properties_json
        LIMIT 1
        """,
        {'cid': claim_id},
    )
    if not claim_rows:
        return json.dumps({
            'error': f'Claim node not found for id: {claim_id}',
            'sessions_exceeding_threshold': [],
        })

    claim_node_id: str = claim_rows[0]['node_id']

    # ------------------------------------------------------------------
    # 2. Find the insured Person node (direct neighbour, then 2-hop)
    # ------------------------------------------------------------------
    insured_rows = rq(
        """
        MATCH (c:Entity {node_id: $cid})-[r:GRAPH_EDGE]-(p:Entity)
        WHERE p.node_type IN ['Person', 'Insured']
           OR toLower(r.edge_type) CONTAINS 'insured'
           OR toLower(r.edge_type) CONTAINS 'covered'
        RETURN p.node_id       AS node_id,
               p.node_type     AS node_type,
               p.label         AS label,
               p.properties_json AS properties_json
        LIMIT 1
        """,
        {'cid': claim_node_id},
    )

    # Fallback: any Person within 2 hops
    if not insured_rows:
        insured_rows = rq(
            """
            MATCH (c:Entity {node_id: $cid})-[:GRAPH_EDGE*1..2]-(p:Entity)
            WHERE p.node_type = 'Person'
            RETURN p.node_id       AS node_id,
                   p.node_type     AS node_type,
                   p.label         AS label,
                   p.properties_json AS properties_json
            LIMIT 1
            """,
            {'cid': claim_node_id},
        )

    insured_node_id: str | None = None
    ins_lat: float | None = None
    ins_lon: float | None = None

    if insured_rows:
        insured_props = _parse(insured_rows[0])
        insured_node_id = insured_rows[0]['node_id']
        ins_lat, ins_lon = _extract_latlon(insured_props)

        # Try linked Address/Location if no coords on Person directly
        if ins_lat is None or ins_lon is None:
            addr_rows = rq(
                """
                MATCH (p:Entity {node_id: $pid})-[:GRAPH_EDGE]-(a:Entity)
                WHERE a.node_type IN ['Address', 'Location']
                RETURN a.properties_json AS properties_json
                LIMIT 5
                """,
                {'pid': insured_node_id},
            )
            for ar in addr_rows:
                ap = _parse(ar)
                la, lo = _extract_latlon(ap)
                if la is not None and lo is not None:
                    ins_lat, ins_lon = la, lo
                    break

    # ------------------------------------------------------------------
    # 3. Find CareSession nodes linked to the claim (up to 2 hops)
    # ------------------------------------------------------------------
    session_rows = rq(
        """
        MATCH (c:Entity {node_id: $cid})-[:GRAPH_EDGE*1..2]-(s:Entity)
        WHERE toLower(s.node_type) CONTAINS 'caresession'
           OR toLower(s.node_type) CONTAINS 'care_session'
        RETURN DISTINCT
               s.node_id       AS node_id,
               s.node_type     AS node_type,
               s.label         AS label,
               s.properties_json AS properties_json
        LIMIT 200
        """,
        {'cid': claim_node_id},
    )

    if not session_rows:
        return json.dumps({
            'claim_id': claim_id,
            'insured_node': insured_node_id,
            'insured_lat': ins_lat,
            'insured_lon': ins_lon,
            'threshold_miles': threshold,
            'sessions_exceeding_threshold': [],
            'total_sessions_found': 0,
            'note': 'No CareSession nodes found linked to this claim.',
        })

    # ------------------------------------------------------------------
    # 4. For each session, resolve coordinates (direct props or neighbour)
    # ------------------------------------------------------------------
    # Batch-fetch location neighbours for all sessions in one query
    session_ids = [r['node_id'] for r in session_rows]

    loc_rows = rq(
        """
        MATCH (s:Entity)-[:GRAPH_EDGE]-(loc:Entity)
        WHERE s.node_id IN $sids
          AND loc.node_type IN ['Address', 'Location', 'Ping', 'GpsLocation']
        RETURN s.node_id         AS session_id,
               loc.properties_json AS properties_json
        LIMIT 1000
        """,
        {'sids': session_ids},
    )

    # Build map: session_id -> list of location prop dicts
    from collections import defaultdict
    session_loc_map: dict[str, list[dict]] = defaultdict(list)
    for lr in loc_rows:
        session_loc_map[lr['session_id']].append(_parse(lr))

    # ------------------------------------------------------------------
    # 5. Compute distances and classify sessions
    # ------------------------------------------------------------------
    all_session_results: list[dict] = []
    sessions_exceeding: list[dict] = []

    for row in session_rows:
        sid = row['node_id']
        props = _parse(row)

        # Try direct coordinates on session node
        s_lat, s_lon = _extract_latlon(props)

        # Fallback to linked location nodes
        if (s_lat is None or s_lon is None) and sid in session_loc_map:
            for lp in session_loc_map[sid]:
                la, lo = _extract_latlon(lp)
                if la is not None and lo is not None:
                    s_lat, s_lon = la, lo
                    break

        # Determine distance
        distance_miles: float | None = None
        distance_method: str = 'unavailable'

        if ins_lat is not None and ins_lon is not None and s_lat is not None and s_lon is not None:
            distance_miles = round(_haversine(ins_lat, ins_lon, s_lat, s_lon), 4)
            distance_method = 'haversine'
        elif ins_lat is None or ins_lon is None:
            distance_method = 'no_insured_coords'
        else:
            distance_method = 'no_session_coords'

        exceeds = distance_miles is not None and distance_miles > threshold

        # Clean props snapshot (exclude internal/label keys)
        props_snapshot = {
            k: v for k, v in props.items()
            if not k.startswith('_') and k != 'label'
        }

        summary = {
            'session_id': sid,
            'session_label': props.get('label') or props.get('session_id') or sid,
            'session_lat': s_lat,
            'session_lon': s_lon,
            'distance_miles': distance_miles,
            'distance_method': distance_method,
            'exceeds_threshold': exceeds,
            'props_snapshot': props_snapshot,
        }
        all_session_results.append(summary)
        if exceeds:
            sessions_exceeding.append(summary)

    # Sort: sessions with distances first (descending), then those without
    all_session_results.sort(
        key=lambda x: (x['distance_miles'] is None, -(x['distance_miles'] or 0))
    )

    return json.dumps({
        'claim_id': claim_id,
        'insured_node': insured_node_id,
        'insured_lat': ins_lat,
        'insured_lon': ins_lon,
        'threshold_miles': threshold,
        'total_sessions_found': len(session_rows),
        'count_exceeding_threshold': len(sessions_exceeding),
        'sessions_exceeding_threshold': sessions_exceeding,
        'all_sessions_ranked_by_distance': all_session_results,
    })