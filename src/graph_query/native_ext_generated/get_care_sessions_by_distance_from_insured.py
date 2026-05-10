"""get_care_sessions_by_distance_from_insured — Neo4j/Cypher native implementation.

Given a claim_id, finds the insured Person node linked to that claim, retrieves
their address coordinates/location, then finds all CareSession nodes linked to
the claim and retrieves each session's check-out location. Ranks sessions by
geographic distance (Haversine if lat/lon available, else falls back to string
comparison) from the insured's address and returns the furthest session along
with all sessions ranked by distance.
"""
from __future__ import annotations

import json
import math
from typing import Any, Optional

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two lat/lon points."""
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _try_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract_lat_lon(props: dict) -> tuple[Optional[float], Optional[float]]:
    lat = _try_float(props.get('latitude') or props.get('lat'))
    lon = _try_float(props.get('longitude') or props.get('lon') or props.get('lng'))
    return lat, lon


def _extract_checkout_latlon(props: dict) -> tuple[Optional[float], Optional[float]]:
    lat = None
    for k in ('checkout_lat', 'check_out_lat', 'checkout_latitude', 'checkin_lat'):
        lat = _try_float(props.get(k))
        if lat is not None:
            break
    lon = None
    for k in ('checkout_lon', 'check_out_lon', 'checkout_longitude', 'checkin_lon'):
        lon = _try_float(props.get(k))
        if lon is not None:
            break
    return lat, lon


def _extract_checkout_addr(props: dict) -> Optional[str]:
    for k in ('checkout_address', 'check_out_address', 'location', 'address'):
        v = props.get(k)
        if v:
            return str(v)
    return None


def _addr_str_from_props(label: str, props: dict) -> str:
    parts = []
    for key in ('address', 'street', 'street_address', 'city', 'state', 'zip', 'zip_code', 'full_address'):
        v = props.get(key)
        if v:
            parts.append(str(v))
    if label:
        parts.insert(0, label)
    return ', '.join(parts) if parts else str(props)


def _safe_props(raw: Any) -> dict:
    """Parse properties_json into a dict safely."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return parse_properties_json(raw)
        except Exception:
            try:
                return json.loads(raw)
            except Exception:
                return {}
    return {}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_native(tool_input: dict[str, Any]) -> str:  # noqa: C901
    claim_id: str = (tool_input.get('claim_id') or '').strip()
    if not claim_id:
        return json.dumps({'error': 'claim_id is required'})

    # ------------------------------------------------------------------
    # Step 1: Locate the claim node
    # ------------------------------------------------------------------
    claim_rows = rq(
        """
        MATCH (c:Entity)
        WHERE c.node_id = $cid
           OR c.label   = $cid
           OR (c.properties_json IS NOT NULL AND c.properties_json CONTAINS $cid)
        RETURN c.node_id        AS node_id,
               c.node_type      AS node_type,
               c.label          AS label,
               c.properties_json AS props_json
        LIMIT 5
        """,
        {'cid': claim_id},
    )

    # Filter to the best match
    claim_row = None
    for row in claim_rows:
        props = _safe_props(row.get('props_json'))
        if (row.get('node_id') == claim_id
                or row.get('label') == claim_id
                or props.get('claim_id') == claim_id
                or props.get('claim_number') == claim_id):
            claim_row = row
            break
    if claim_row is None and claim_rows:
        claim_row = claim_rows[0]

    if claim_row is None:
        return json.dumps({'error': f'Claim not found: {claim_id}', 'claim_id': claim_id})

    claim_nid: str = claim_row['node_id']

    # ------------------------------------------------------------------
    # Step 2a: Find insured Person node (1-hop from claim)
    # ------------------------------------------------------------------
    insured_rows = rq(
        """
        MATCH (c:Entity {node_id: $cnid})-[r:GRAPH_EDGE]-(p:Entity)
        WHERE p.node_type IN ['Person', 'Insured', 'Customer']
        RETURN p.node_id        AS node_id,
               p.node_type      AS node_type,
               p.label          AS label,
               p.properties_json AS props_json,
               r.edge_type      AS edge_type
        LIMIT 10
        """,
        {'cnid': claim_nid},
    )

    insured_row = None
    insured_edge_type = ''
    INSURED_KEYWORDS = ('INSUR', 'CLAIMANT', 'COVERED', 'PERSON', 'FILED', 'HOLD')
    for row in insured_rows:
        et = (row.get('edge_type') or '').upper()
        if any(kw in et for kw in INSURED_KEYWORDS):
            insured_row = row
            insured_edge_type = et
            break
    if insured_row is None and insured_rows:
        insured_row = insured_rows[0]
        insured_edge_type = (insured_row.get('edge_type') or '').upper()

    # ------------------------------------------------------------------
    # Step 2b: If no insured found, try 2-hop via Policy
    # ------------------------------------------------------------------
    if insured_row is None:
        insured_rows_2hop = rq(
            """
            MATCH (c:Entity {node_id: $cnid})-[:GRAPH_EDGE]-(pol:Entity)
            WHERE pol.node_type CONTAINS 'Policy' OR pol.node_type CONTAINS 'Polic'
            MATCH (pol)-[:GRAPH_EDGE]-(p:Entity)
            WHERE p.node_type IN ['Person', 'Insured', 'Customer']
            RETURN p.node_id        AS node_id,
                   p.node_type      AS node_type,
                   p.label          AS label,
                   p.properties_json AS props_json,
                   '' AS edge_type
            LIMIT 5
            """,
            {'cnid': claim_nid},
        )
        if insured_rows_2hop:
            insured_row = insured_rows_2hop[0]

    insured_nid = insured_row['node_id'] if insured_row else None
    insured_props = _safe_props(insured_row.get('props_json')) if insured_row else {}
    insured_label = (insured_row.get('label') or '') if insured_row else ''

    # ------------------------------------------------------------------
    # Step 3: Get insured's address / lat-lon
    # ------------------------------------------------------------------
    insured_lat, insured_lon = _extract_lat_lon(insured_props)
    insured_addr_str = None

    if insured_nid:
        addr_rows = rq(
            """
            MATCH (p:Entity {node_id: $pnid})-[:GRAPH_EDGE]-(a:Entity)
            WHERE a.node_type CONTAINS 'Addr'
               OR a.node_type CONTAINS 'Location'
               OR a.node_type CONTAINS 'Address'
            RETURN a.node_id        AS node_id,
                   a.node_type      AS node_type,
                   a.label          AS label,
                   a.properties_json AS props_json
            LIMIT 5
            """,
            {'pnid': insured_nid},
        )
        for arow in addr_rows:
            ap = _safe_props(arow.get('props_json'))
            lat, lon = _extract_lat_lon(ap)
            if lat is not None and lon is not None and insured_lat is None:
                insured_lat, insured_lon = lat, lon
            if insured_addr_str is None:
                insured_addr_str = _addr_str_from_props(arow.get('label') or '', ap)
            break  # first address node wins

    if insured_addr_str is None:
        insured_addr_str = _addr_str_from_props(insured_label, insured_props)

    # ------------------------------------------------------------------
    # Step 4a: Find CareSession nodes — 1-hop from claim
    # ------------------------------------------------------------------
    care_rows_1hop = rq(
        """
        MATCH (c:Entity {node_id: $cnid})-[r:GRAPH_EDGE]-(cs:Entity)
        WHERE cs.node_type CONTAINS 'Care'
           OR cs.node_type CONTAINS 'Session'
        RETURN cs.node_id        AS node_id,
               cs.node_type      AS node_type,
               cs.label          AS label,
               cs.properties_json AS props_json
        LIMIT 50
        """,
        {'cnid': claim_nid},
    )

    # Step 4b: 2-hop if none found
    care_rows_2hop = []
    if not care_rows_1hop:
        care_rows_2hop = rq(
            """
            MATCH (c:Entity {node_id: $cnid})-[:GRAPH_EDGE]-(mid:Entity)-[:GRAPH_EDGE]-(cs:Entity)
            WHERE cs.node_type CONTAINS 'Care'
               OR cs.node_type CONTAINS 'Session'
            RETURN DISTINCT
                   cs.node_id        AS node_id,
                   cs.node_type      AS node_type,
                   cs.label          AS label,
                   cs.properties_json AS props_json
            LIMIT 50
            """,
            {'cnid': claim_nid},
        )

    care_rows = care_rows_1hop or care_rows_2hop

    if not care_rows:
        return json.dumps({
            'claim_id': claim_id,
            'claim_node_id': claim_nid,
            'insured_node_id': insured_nid,
            'insured_address': insured_addr_str,
            'insured_lat': insured_lat,
            'insured_lon': insured_lon,
            'care_sessions': [],
            'furthest_session': None,
            'all_sessions_ranked_by_distance': [],
            'total_sessions_found': 0,
            'note': 'No CareSession nodes found linked to this claim within 2 hops.',
        })

    # ------------------------------------------------------------------
    # Step 5: For each CareSession, find check-out location
    # ------------------------------------------------------------------
    sessions_info: list[dict] = []
    seen_nids: set[str] = set()

    for csrow in care_rows:
        cs_nid: str = csrow['node_id']
        if cs_nid in seen_nids:
            continue
        seen_nids.add(cs_nid)

        cs_props = _safe_props(csrow.get('props_json'))
        cs_label = csrow.get('label') or cs_nid
        cs_type  = csrow.get('node_type') or 'CareSession'

        # Try checkout lat/lon directly on the session node
        checkout_lat, checkout_lon = _extract_checkout_latlon(cs_props)
        checkout_addr_str = _extract_checkout_addr(cs_props)
        checkout_node_id = None

        # Traverse neighbours of the CareSession for address/checkout location nodes
        loc_rows = rq(
            """
            MATCH (cs:Entity {node_id: $csnid})-[r:GRAPH_EDGE]-(loc:Entity)
            WHERE loc.node_type CONTAINS 'Addr'
               OR loc.node_type CONTAINS 'Location'
               OR loc.node_type CONTAINS 'Address'
               OR loc.node_type CONTAINS 'Checkout'
               OR r.edge_type CONTAINS 'CHECKOUT'
               OR r.edge_type CONTAINS 'CHECK_OUT'
            RETURN loc.node_id        AS node_id,
                   loc.node_type      AS node_type,
                   loc.label          AS label,
                   loc.properties_json AS props_json,
                   r.edge_type        AS edge_type
            LIMIT 10
            """,
            {'csnid': cs_nid},
        )

        for lrow in loc_rows:
            lp = _safe_props(lrow.get('props_json'))
            lat, lon = _extract_lat_lon(lp)
            if lat is not None and lon is not None and checkout_lat is None:
                checkout_lat = lat
                checkout_lon = lon
                checkout_node_id = lrow['node_id']
            if checkout_addr_str is None:
                checkout_addr_str = _addr_str_from_props(lrow.get('label') or '', lp)
                checkout_node_id = checkout_node_id or lrow['node_id']

        # Compute distance
        distance: Optional[float] = None
        distance_method = 'none'

        if (insured_lat is not None and insured_lon is not None
                and checkout_lat is not None and checkout_lon is not None):
            distance = _haversine(insured_lat, insured_lon, checkout_lat, checkout_lon)
            distance_method = 'haversine_miles'
        elif insured_addr_str and checkout_addr_str:
            distance = (0.0
                        if insured_addr_str.strip().lower() == checkout_addr_str.strip().lower()
                        else 1.0)
            distance_method = 'address_mismatch_proxy'

        sessions_info.append({
            'session_id': cs_nid,
            'session_label': cs_label,
            'session_type': cs_type,
            'checkout_address': checkout_addr_str,
            'checkout_lat': checkout_lat,
            'checkout_lon': checkout_lon,
            'checkout_location_node_id': checkout_node_id,
            'distance_from_insured': distance,
            'distance_method': distance_method,
            'session_properties': dict(list(cs_props.items())[:10]),
        })

    # ------------------------------------------------------------------
    # Step 6: Rank by distance descending (None last)
    # ------------------------------------------------------------------
    with_dist    = [s for s in sessions_info if s['distance_from_insured'] is not None]
    without_dist = [s for s in sessions_info if s['distance_from_insured'] is None]
    with_dist.sort(key=lambda x: x['distance_from_insured'], reverse=True)  # type: ignore[arg-type]
    ranked = with_dist + without_dist

    furthest = ranked[0] if ranked else None

    return json.dumps(
        {
            'claim_id': claim_id,
            'claim_node_id': claim_nid,
            'insured_node_id': insured_nid,
            'insured_address': insured_addr_str,
            'insured_lat': insured_lat,
            'insured_lon': insured_lon,
            'furthest_session': furthest,
            'all_sessions_ranked_by_distance': ranked,
            'total_sessions_found': len(sessions_info),
        },
        default=str,
    )