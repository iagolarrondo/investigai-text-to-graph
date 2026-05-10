"""get_claimant_assessment_scores – Neo4j/Cypher native implementation.

Resolves the claimant Person node from a claim, traverses all adjacent
assessment/review/medical-record node types up to 2 hops, and collects
any property whose key contains 'mmse', 'cognitive', 'score', 'assessment',
'test', 'mini', 'mental', or 'exam'. Returns a structured JSON response.
"""
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq
from src.graph_query.neo4j_native_reads import parse_properties_json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCORE_KEY_FRAGS: list[str] = [
    'mmse', 'cognitive', 'score', 'assessment', 'test', 'mini', 'mental', 'exam'
]
MMSE_KEY_FRAGS: list[str] = ['mmse', 'mini', 'mental']
MMSE_PAIRED_FRAGS: list[tuple[str, str]] = [('mental', 'exam')]  # both must appear
ASSESSMENT_TYPE_FRAGS: list[str] = [
    'medicalassessment', 'assessment', 'eligibilityreview', 'review',
    'medicalrecord', 'record', 'evaluation', 'clinicalassessment', 'cognitivetest'
]
CLAIMANT_EDGE_FRAGS: list[str] = [
    'claimant', 'insured', 'filed', 'covered', 'patient', 'member'
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_props(raw: Any) -> dict:
    """Return a plain dict from a properties_json string or existing dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return parse_properties_json(raw)
    except Exception:
        pass
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _extract_scores(props: dict) -> dict:
    """Return sub-dict of props whose keys contain any SCORE_KEY_FRAGS fragment."""
    found: dict = {}
    for k, v in props.items():
        kl = k.lower()
        if any(frag in kl for frag in SCORE_KEY_FRAGS):
            found[k] = v
    return found


def _is_assessment_type(node_type: str) -> bool:
    nt = node_type.lower()
    return any(frag in nt for frag in ASSESSMENT_TYPE_FRAGS)


def _is_mmse_key(key: str) -> bool:
    kl = key.lower()
    if any(frag in kl for frag in MMSE_KEY_FRAGS):
        return True
    for a, b in MMSE_PAIRED_FRAGS:
        if a in kl and b in kl:
            return True
    return False


def _node_record(row: dict) -> dict:
    """Normalise a raw Neo4j row that contains node fields."""
    return {
        'node_id': row.get('node_id', ''),
        'node_type': row.get('node_type', ''),
        'label': row.get('label', row.get('node_id', '')),
        'properties': _parse_props(row.get('properties_json')),
    }


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def run_native(tool_input: dict[str, Any]) -> str:
    """Resolve claimant and collect assessment/score properties for a claim."""
    claim_id: str = str(tool_input.get('claim_id', '')).strip()
    if not claim_id:
        return json.dumps({'error': 'claim_id is required'})

    # ------------------------------------------------------------------
    # Step 1 – Locate the claim node
    # ------------------------------------------------------------------
    claim_rows = rq(
        """
        MATCH (c:Entity)
        WHERE c.node_id = $cid
           OR c.label   = $cid
        RETURN c.node_id        AS node_id,
               c.node_type      AS node_type,
               c.label          AS label,
               c.properties_json AS properties_json
        LIMIT 1
        """,
        {'cid': claim_id},
    )
    if not claim_rows:
        return json.dumps({
            'error': f'Claim node not found for claim_id={claim_id}',
            'claim_id': claim_id,
        })
    claim_rec = _node_record(claim_rows[0])
    claim_node_id: str = claim_rec['node_id']

    # ------------------------------------------------------------------
    # Step 2 – Find claimant Person nodes adjacent to the claim
    # ------------------------------------------------------------------
    person_rows = rq(
        """
        MATCH (c:Entity {node_id: $cnid})-[r:GRAPH_EDGE]-(p:Entity)
        WHERE toLower(p.node_type) = 'person'
        RETURN p.node_id         AS node_id,
               p.node_type       AS node_type,
               p.label           AS label,
               p.properties_json AS properties_json,
               r.edge_type       AS edge_type
        LIMIT 50
        """,
        {'cnid': claim_node_id},
    )

    unique_claimants: list[dict] = []
    seen_claimant_ids: set[str] = set()
    for pr in person_rows:
        nid = pr.get('node_id', '')
        if nid in seen_claimant_ids:
            continue
        seen_claimant_ids.add(nid)
        edge_type = str(pr.get('edge_type', '')).lower()
        role = edge_type if any(frag in edge_type for frag in CLAIMANT_EDGE_FRAGS) else 'person_neighbor'
        unique_claimants.append({
            'node_id': nid,
            'label': pr.get('label', nid),
            'role': role,
        })

    # ------------------------------------------------------------------
    # Step 3 – Collect assessment/score nodes up to 2 hops from claim
    #          and from each claimant person node
    # ------------------------------------------------------------------
    seed_ids: list[str] = [claim_node_id] + [c['node_id'] for c in unique_claimants]

    # Hop-1 neighbours of all seeds
    hop1_rows = rq(
        """
        UNWIND $seeds AS seed_id
        MATCH (seed:Entity {node_id: seed_id})-[:GRAPH_EDGE]-(n1:Entity)
        WHERE n1.node_id <> seed_id
          AND NOT n1.node_id IN $seeds
        RETURN DISTINCT
               n1.node_id         AS node_id,
               n1.node_type       AS node_type,
               n1.label           AS label,
               n1.properties_json AS properties_json,
               1                  AS hop
        LIMIT 200
        """,
        {'seeds': seed_ids},
    )

    hop1_ids = [r.get('node_id', '') for r in hop1_rows if r.get('node_id')]
    all_hop1_ids_set: set[str] = set(hop1_ids)
    exclude_hop2: list[str] = seed_ids + hop1_ids

    # Hop-2 neighbours of hop-1 nodes
    hop2_rows: list[dict] = []
    if hop1_ids:
        hop2_rows = rq(
            """
            UNWIND $h1ids AS h1id
            MATCH (h1:Entity {node_id: h1id})-[:GRAPH_EDGE]-(n2:Entity)
            WHERE NOT n2.node_id IN $excl
            RETURN DISTINCT
                   n2.node_id         AS node_id,
                   n2.node_type       AS node_type,
                   n2.label           AS label,
                   n2.properties_json AS properties_json,
                   2                  AS hop
            LIMIT 400
            """,
            {'h1ids': hop1_ids, 'excl': exclude_hop2},
        )

    # ------------------------------------------------------------------
    # Step 4 – Inspect every candidate node for score properties
    # ------------------------------------------------------------------
    # Build full candidate list:
    #   • claim node itself (hop 0)
    #   • claimant person nodes (hop 0)
    #   • hop-1 neighbours
    #   • hop-2 neighbours
    candidates: list[dict] = []

    # Claim node
    candidates.append({
        'node_id': claim_rec['node_id'],
        'node_type': claim_rec['node_type'],
        'label': claim_rec['label'],
        'hop': 0,
        'props': claim_rec['properties'],
    })

    # Claimant person nodes – fetch full props if not already in hand
    claimant_prop_rows = rq(
        """
        UNWIND $ids AS nid
        MATCH (p:Entity {node_id: nid})
        RETURN p.node_id AS node_id, p.node_type AS node_type,
               p.label AS label, p.properties_json AS properties_json
        """,
        {'ids': list(seen_claimant_ids)},
    ) if seen_claimant_ids else []
    claimant_props_by_id: dict[str, dict] = {
        r['node_id']: _parse_props(r.get('properties_json')) for r in claimant_prop_rows
    }
    for c in unique_claimants:
        candidates.append({
            'node_id': c['node_id'],
            'node_type': 'Person',
            'label': c['label'],
            'hop': 0,
            'props': claimant_props_by_id.get(c['node_id'], {}),
        })

    visited_candidate_ids: set[str] = {claim_node_id} | seen_claimant_ids

    for row in hop1_rows + hop2_rows:
        nid = row.get('node_id', '')
        if not nid or nid in visited_candidate_ids:
            continue
        visited_candidate_ids.add(nid)
        candidates.append({
            'node_id': nid,
            'node_type': row.get('node_type', ''),
            'label': row.get('label', nid),
            'hop': row.get('hop', 1),
            'props': _parse_props(row.get('properties_json')),
        })

    # ------------------------------------------------------------------
    # Step 5 – Classify candidates
    # ------------------------------------------------------------------
    assessment_nodes_found: list[dict] = []
    score_properties: list[dict] = []
    seen_score_node_ids: set[str] = set()

    for cand in candidates:
        scores = _extract_scores(cand['props'])
        is_assessment = _is_assessment_type(cand['node_type'])

        if is_assessment or scores:
            assessment_nodes_found.append({
                'node_id': cand['node_id'],
                'node_type': cand['node_type'],
                'label': cand['label'],
                'hop': cand['hop'],
            })

        if scores and cand['node_id'] not in seen_score_node_ids:
            seen_score_node_ids.add(cand['node_id'])
            score_properties.append({
                'source_node_id': cand['node_id'],
                'source_node_type': cand['node_type'],
                'source_label': cand['label'],
                'hop': cand['hop'],
                'scores': scores,
            })

    # ------------------------------------------------------------------
    # Step 6 – Extract MMSE-specific highlights
    # ------------------------------------------------------------------
    mmse_results: list[dict] = []
    for sp in score_properties:
        for k, v in sp.get('scores', {}).items():
            if _is_mmse_key(k):
                mmse_results.append({
                    'node_id': sp['source_node_id'],
                    'node_type': sp['source_node_type'],
                    'node_label': sp['source_label'],
                    'property': k,
                    'value': v,
                })

    # ------------------------------------------------------------------
    # Step 7 – Build and return result
    # ------------------------------------------------------------------
    total_visited = len(visited_candidate_ids)

    if mmse_results:
        summary = (
            f"Found {len(mmse_results)} MMSE/cognitive score(s) across "
            f"{len(score_properties)} node(s) for claim {claim_id}. "
            f"Claimant candidates: {len(unique_claimants)}."
        )
    else:
        summary = (
            f"No MMSE or cognitive score properties found in the 2-hop "
            f"neighborhood of claim {claim_id}. "
            f"Checked {total_visited} nodes total. "
            f"Assessment-type nodes found: {len(assessment_nodes_found)}."
        )

    result = {
        'claim_id': claim_id,
        'claim_node_id': claim_node_id,
        'claimant_nodes': unique_claimants,
        'mmse_scores': mmse_results,
        'all_assessment_score_properties': score_properties,
        'assessment_nodes_found': assessment_nodes_found,
        'summary': summary,
    }
    return json.dumps(result, default=str)