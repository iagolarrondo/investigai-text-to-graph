"""
Regression: explicit graph node ids in mixed questions must stay anchored.

Previously, ``question_already_has_node_ids`` skipped all pre-planner entity resolution,
so ambiguous names were never disambiguated; overlapping mentions (e.g. ``person`` inside
``person_5056``) could also be searched as names, leading the planner to claim the real
id was missing.
"""

from __future__ import annotations

import networkx as nx

from src.app.entity_resolution import (
    append_verified_graph_node_hint,
    filter_mentions_excluding_graph_anchors,
    unresolved_graph_like_id_tokens,
    verified_graph_anchor_spans,
    verified_graph_node_ids_in_question,
)


def _minimal_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("person_5056", node_type="Person", label="Anchor Person")
    G.add_node("person_7001", node_type="Person", label="MARIA CHEN")
    G.add_node("person_7002", node_type="Person", label="MARIA CHEN")
    return G


def test_verified_anchor_for_follow_up_snake_case_id():
    G = _minimal_graph()
    q = "Is person_5056 related to MARIA CHEN?"
    spans = verified_graph_anchor_spans(q, G)
    assert len(spans) == 1
    start, end, canon = spans[0]
    assert q[start:end] == "person_5056"
    assert canon == "person_5056"


def test_filter_removes_substring_mention_overlapping_verified_id():
    """``person`` as a mention must not be name-searched when it lies inside ``person_5056``."""
    G = _minimal_graph()
    q = "Is person_5056 related to MARIA CHEN?"
    mentions = [
        {"mention": "person", "node_type_hint": "Person"},
        {"mention": "MARIA CHEN", "node_type_hint": "Person"},
    ]
    filtered = filter_mentions_excluding_graph_anchors(q, mentions, G)
    assert [m["mention"] for m in filtered] == ["MARIA CHEN"]


def test_mixed_question_keeps_maria_for_disambiguation_only():
    """Explicit id side is anchored; only the capitalized name side remains for ER."""
    G = _minimal_graph()
    q = "Is person_5056 related to MARIA CHEN?"
    mentions = [{"mention": "MARIA CHEN", "node_type_hint": "Person"}]
    filtered = filter_mentions_excluding_graph_anchors(q, mentions, G)
    assert len(filtered) == 1


def test_append_planner_hint_lists_verified_ids():
    G = _minimal_graph()
    q = "Is person_5056 related to MARIA CHEN?"
    hinted = append_verified_graph_node_hint(q, G)
    assert hinted.startswith(q.rstrip())
    assert "person_5056" in hinted
    assert "--- Verified graph node ids ---" in hinted
    assert "exist** in the loaded graph" in hinted or "exist" in hinted


def test_append_hint_idempotent_when_marker_already_present():
    G = _minimal_graph()
    q0 = "Is person_5056 related to MARIA CHEN?"
    once = append_verified_graph_node_hint(q0, G)
    twice = append_verified_graph_node_hint(once, G)
    assert twice == once


def test_unresolved_id_like_token_detected():
    G = _minimal_graph()
    q = "Compare person_5056 to claim_NOTINGRAPH_999."
    bad = unresolved_graph_like_id_tokens(q, G)
    assert "claim_NOTINGRAPH_999" in bad
    assert "person_5056" not in bad


def test_verified_graph_node_ids_ordered_unique():
    G = _minimal_graph()
    q = "person_5056 and Person|5056 same?"
    ids = verified_graph_node_ids_in_question(q, G)
    assert ids == ["person_5056"]
