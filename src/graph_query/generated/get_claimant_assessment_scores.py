"""Auto-generated graph tool extension (registry)."""
from __future__ import annotations

import json
from typing import Any

from src.graph_query.query_graph import get_graph


def run(tool_input: dict[str, Any]) -> str:
    """Registry entrypoint; return JSON or plain text for the planner."""
    from src.graph_query.native_read_mode import neo4j_native_reads_enabled

    if neo4j_native_reads_enabled():
        from src.graph_query.neo4j_native_extensions import run_extension_native

        return run_extension_native("get_claimant_assessment_scores", tool_input)

    G = get_graph()

    # Score-related property key fragments to search for
    SCORE_KEYS = ['mmse', 'cognitive', 'score', 'assessment', 'test', 'mini', 'mental', 'exam']
    # Node types likely to carry assessment data
    ASSESSMENT_TYPES = ['medicalassessment', 'assessment', 'eligibilityreview', 'review', 'medicalrecord', 'record', 'evaluation', 'clinicalassessment', 'cognitivetest']

    # Step 1: Locate the claim node
    claim_node_id = None
    for nid, data in G.nodes(data=True):
        label = str(data.get('label', '')).strip()
        ntype = str(data.get('node_type', '')).strip()
        if label == claim_id or nid == claim_id:
            claim_node_id = nid
            break
        # Also try matching on id property
        if str(data.get('id', '')) == claim_id:
            claim_node_id = nid
            break

    if claim_node_id is None:
        return json.dumps({'error': f'Claim node not found for claim_id={claim_id}', 'claim_id': claim_id})

    # Step 2: Find claimant Person node(s) linked to this claim
    claimant_nodes = []
    # Check direct neighbors of the claim
    neighbors_to_check = set()
    neighbors_to_check.update(G.successors(claim_node_id))
    neighbors_to_check.update(G.predecessors(claim_node_id))

    for nid in neighbors_to_check:
        ndata = G.nodes[nid]
        ntype = str(ndata.get('node_type', '')).lower()
        if ntype == 'person':
            # Check if the edge has a claimant-related role
            edge_data_fwd = G.get_edge_data(claim_node_id, nid) or {}
            edge_data_rev = G.get_edge_data(nid, claim_node_id) or {}
            for ed in [edge_data_fwd, edge_data_rev]:
                rel = str(ed.get('relationship', ed.get('edge_type', ed.get('label', '')))).lower()
                if any(k in rel for k in ['claimant', 'insured', 'filed', 'covered', 'patient', 'member']):
                    claimant_nodes.append({'node_id': nid, 'label': ndata.get('label', nid), 'role': rel})
                    break
            else:
                # Add all person nodes as candidates if no claimant found yet
                claimant_nodes.append({'node_id': nid, 'label': ndata.get('label', nid), 'role': 'person_neighbor'})

    # Deduplicate
    seen_ids = set()
    unique_claimants = []
    for c in claimant_nodes:
        if c['node_id'] not in seen_ids:
            seen_ids.add(c['node_id'])
            unique_claimants.append(c)

    # Step 3: Gather all nodes to traverse for assessments
    # Start from claim node and all claimant person nodes
    seed_nodes = [claim_node_id] + [c['node_id'] for c in unique_claimants]

    visited = set(seed_nodes)
    assessment_nodes = []
    score_properties = []

    def extract_scores(nid, ndata):
        found = {}
        for k, v in ndata.items():
            kl = k.lower()
            if any(frag in kl for frag in SCORE_KEYS):
                found[k] = v
        return found

    # Check score properties on the claim node itself
    claim_scores = extract_scores(claim_node_id, G.nodes[claim_node_id])
    if claim_scores:
        score_properties.append({
            'source_node_id': claim_node_id,
            'source_node_type': G.nodes[claim_node_id].get('node_type', ''),
            'source_label': G.nodes[claim_node_id].get('label', claim_node_id),
            'scores': claim_scores
        })

    # Traverse 2-hop neighborhood from each seed node
    for seed in seed_nodes:
        hop1 = set(G.successors(seed)) | set(G.predecessors(seed))
        for nid1 in hop1:
            if nid1 in visited:
                continue
            visited.add(nid1)
            ndata1 = G.nodes[nid1]
            ntype1 = str(ndata1.get('node_type', '')).lower()

            # Check scores on this node
            scores1 = extract_scores(nid1, ndata1)
            is_assessment1 = any(at in ntype1 for at in ASSESSMENT_TYPES)

            if scores1 or is_assessment1:
                entry = {
                    'source_node_id': nid1,
                    'source_node_type': ndata1.get('node_type', ''),
                    'source_label': ndata1.get('label', nid1),
                    'hop': 1,
                    'scores': scores1
                }
                if scores1 or is_assessment1:
                    assessment_nodes.append(entry)
                if scores1:
                    score_properties.append(entry)

            # Hop 2
            hop2 = set(G.successors(nid1)) | set(G.predecessors(nid1))
            for nid2 in hop2:
                if nid2 in visited:
                    continue
                visited.add(nid2)
                ndata2 = G.nodes[nid2]
                ntype2 = str(ndata2.get('node_type', '')).lower()

                scores2 = extract_scores(nid2, ndata2)
                is_assessment2 = any(at in ntype2 for at in ASSESSMENT_TYPES)

                if scores2 or is_assessment2:
                    entry2 = {
                        'source_node_id': nid2,
                        'source_node_type': ndata2.get('node_type', ''),
                        'source_label': ndata2.get('label', nid2),
                        'hop': 2,
                        'scores': scores2
                    }
                    if scores2 or is_assessment2:
                        assessment_nodes.append(entry2)
                    if scores2:
                        score_properties.append(entry2)

    # Check score properties directly on claimant person nodes
    for c in unique_claimants:
        ndata = G.nodes[c['node_id']]
        scores = extract_scores(c['node_id'], ndata)
        if scores:
            score_properties.append({
                'source_node_id': c['node_id'],
                'source_node_type': 'Person',
                'source_label': ndata.get('label', c['node_id']),
                'hop': 0,
                'scores': scores
            })

    # Deduplicate score_properties by node_id
    seen_score_ids = set()
    unique_scores = []
    for sp in score_properties:
        if sp['source_node_id'] not in seen_score_ids:
            seen_score_ids.add(sp['source_node_id'])
            unique_scores.append(sp)

    # Build summary
    mmse_results = []
    for sp in unique_scores:
        for k, v in sp.get('scores', {}).items():
            if 'mmse' in k.lower() or 'mini' in k.lower() or ('mental' in k.lower() and 'exam' in k.lower()):
                mmse_results.append({
                    'node_id': sp['source_node_id'],
                    'node_type': sp['source_node_type'],
                    'node_label': sp['source_label'],
                    'property': k,
                    'value': v
                })

    result = {
        'claim_id': claim_id,
        'claim_node_id': claim_node_id,
        'claimant_nodes': unique_claimants,
        'mmse_scores': mmse_results,
        'all_assessment_score_properties': unique_scores,
        'assessment_nodes_found': [
            {'node_id': a['source_node_id'], 'node_type': a['source_node_type'], 'label': a['source_label'], 'hop': a['hop']}
            for a in assessment_nodes
        ],
        'summary': (
            f"Found {len(mmse_results)} MMSE/cognitive score(s) across {len(unique_scores)} node(s) "
            f"for claim {claim_id}. Claimant candidates: {len(unique_claimants)}."
        ) if mmse_results else (
            f"No MMSE or cognitive score properties found in the 2-hop neighborhood of claim {claim_id}. "
            f"Checked {len(visited)} nodes total. "
            f"Assessment-type nodes found: {len(assessment_nodes)}."
        )
    }
    return json.dumps(result, default=str)
