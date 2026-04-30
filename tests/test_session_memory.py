from __future__ import annotations

from src.llm.tool_agent import ToolAgentResult, ToolAgentStep
from src.session.memory import build_memory_digest, build_turn_from_result, serialize_turn


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
        },
    ]
    digest = build_memory_digest(turns, last_n=2)
    assert digest.turn_count == 2
    assert digest.recent_questions == ["Q1", "Q2"]
    assert "Claim|C1" in digest.recent_focus_node_ids
    assert "Policy|POL1" in digest.recent_anchor_ids

