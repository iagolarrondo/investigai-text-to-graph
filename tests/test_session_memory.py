from __future__ import annotations

from src.llm.tool_agent import ToolAgentResult, ToolAgentStep
from src.session.memory import (
    build_memory_digest,
    build_turn_from_result,
    extend_referents_with_node_ids,
    infer_active_referents,
    merge_session_referents,
    serialize_turn,
)


def test_build_turn_from_result_captures_focus_and_anchors() -> None:
    tr = ToolAgentResult(
        question="q",
        steps=[ToolAgentStep(tool="search_nodes", input={"query": "x"}, result_preview="Person|1004")],
        final_text="Answer with Policy|POL001",
        graph_focus_node_id="Person|1004",
    )
    turn = build_turn_from_result(
        turn_id=1,
        user_question="Who is this person?",
        investigation_question="Who is Person|1004?",
        result=tr,
    )
    row = serialize_turn(turn)
    assert row["turn_id"] == 1
    assert row["graph_focus_node_id"] == "Person|1004"
    assert "Person|1004" in row["anchors"]
    assert "Policy|POL001" in row["anchors"]
    assert row.get("active_referents", {}).get("primary_person") == "Person|1004"
    assert isinstance(row.get("answer_summary_bullets"), list)


def test_build_memory_digest_recent_rollup() -> None:
    turns = [
        {
            "turn_id": 1,
            "created_at_utc": "2026-01-01T00:00:00+00:00",
            "user_question": "Q1",
            "investigation_question": "Q1",
            "final_answer": "A1",
            "graph_focus_node_id": "Person|1004",
            "anchors": ["Person|1004", "Claim|C1"],
            "reviewer_notes": [],
            "synthesis_rationale": "",
            "active_referents": {},
            "answer_summary_bullets": [],
        },
        {
            "turn_id": 2,
            "created_at_utc": "2026-01-01T00:01:00+00:00",
            "user_question": "Q2",
            "investigation_question": "Q2",
            "final_answer": "A2",
            "graph_focus_node_id": "Claim|C1",
            "anchors": ["Claim|C1", "Policy|POL1"],
            "reviewer_notes": [],
            "synthesis_rationale": "",
            "active_referents": {},
            "answer_summary_bullets": [],
        },
    ]
    digest = build_memory_digest(turns, last_n=2)
    assert digest.turn_count == 2
    assert digest.recent_questions == ["Q1", "Q2"]
    assert "Claim|C1" in digest.recent_focus_node_ids
    assert "Policy|POL1" in digest.recent_anchor_ids


def test_infer_active_referents_keeps_all_ids_per_kind() -> None:
    refs = infer_active_referents(["Person|1", "Person|2", "Claim|C1"], None)
    assert refs.get("primary_person") == "Person|1"
    assert refs.get("ids_person") == ["Person|1", "Person|2"]
    assert refs.get("ids_claim") == ["Claim|C1"]


def test_infer_active_referents_sets_primary_address() -> None:
    refs = infer_active_referents(["Person|1", "address_9002"], "address_9002")
    assert refs.get("primary_address") == "address_9002"
    assert refs.get("primary_person") == "Person|1"


def test_infer_active_referents_sets_primary_business() -> None:
    refs = infer_active_referents(["Person|1004", "Business|ACME"], "Business|ACME")
    assert refs.get("primary_business") == "Business|ACME"
    assert refs.get("primary_person") == "Person|1004"


def test_merge_session_referents_carries_forward() -> None:
    a = merge_session_referents({}, {"primary_person": "Person|1"})
    b = merge_session_referents(a, {"primary_claim": "Claim|C2"})
    assert b["primary_person"] == "Person|1"
    assert b["primary_claim"] == "Claim|C2"


def test_merge_session_referents_merges_id_lists_new_first() -> None:
    prior = {"ids_person": ["Person|A", "Person|B"]}
    nxt = {"ids_person": ["Person|C", "Person|A"]}
    out = merge_session_referents(prior, nxt)
    assert out["ids_person"] == ["Person|C", "Person|A", "Person|B"]


def test_extend_referents_prioritizes_selection_then_other_candidates() -> None:
    refs = {"primary_person": "Person|Seed", "ids_person": ["Person|Seed"]}
    out = extend_referents_with_node_ids(
        refs,
        additional_ids=["Person|A", "Person|B"],
        priority_ids=["Person|B"],
    )
    assert out["ids_person"][0] == "Person|B"
    assert "Person|A" in out["ids_person"]
    assert "Person|Seed" in out["ids_person"]


def test_digest_rollup_includes_active_referents_ids_without_anchors() -> None:
    turns = [
        {
            "turn_id": 1,
            "created_at_utc": "2026-01-01T00:00:00+00:00",
            "user_question": "Q1",
            "investigation_question": "Q1",
            "final_answer": "A1",
            "graph_focus_node_id": None,
            "anchors": [],
            "reviewer_notes": [],
            "synthesis_rationale": "",
            "active_referents": {"ids_person": ["Person|X", "Person|Y"]},
            "answer_summary_bullets": [],
        },
    ]
    digest = build_memory_digest(turns, last_n=3)
    rolled = digest.recent_entity_ids_by_kind.get("person", ())
    assert "Person|X" in rolled and "Person|Y" in rolled

