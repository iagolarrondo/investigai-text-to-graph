from __future__ import annotations

from src.session.context_resolver import resolve_question_with_session_memory


def _turn(
    turn_id: int,
    user_q: str,
    inv_q: str,
    answer: str,
    focus: str | None,
    anchors: list[str],
) -> dict:
    return {
        "turn_id": turn_id,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "user_question": user_q,
        "investigation_question": inv_q,
        "final_answer": answer,
        "graph_focus_node_id": focus,
        "anchors": anchors,
        "reviewer_notes": [],
        "synthesis_rationale": "",
    }


def test_pass_through_standalone_question() -> None:
    turns = [_turn(1, "Who is Person|1004?", "Who is Person|1004?", "A", "Person|1004", ["Person|1004"])]
    d = resolve_question_with_session_memory("Find suspicious shared bank accounts in Quincy", turns)
    assert d.action == "pass_through"
    assert d.resolved_question == "Find suspicious shared bank accounts in Quincy"


def test_rewrite_clear_contextual_claim_reference() -> None:
    turns = [_turn(1, "Explain this claim", "Explain Claim|C001", "A", "Claim|C001", ["Claim|C001"])]
    d = resolve_question_with_session_memory("What about that claim's policy links?", turns)
    assert d.action == "rewrite"
    assert "Claim|C001" in d.resolved_question

