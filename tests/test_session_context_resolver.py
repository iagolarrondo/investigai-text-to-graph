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
        "active_referents": {},
        "answer_summary_bullets": [],
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


def test_rewrite_that_business_when_single_in_session() -> None:
    turns = [_turn(1, "Prior", "Prior", "Ans", "Business|B1", ["Business|B1"])]
    d = resolve_question_with_session_memory("Who owns that business?", turns)
    assert d.action == "rewrite"
    assert "Business|B1" in d.resolved_question


def test_clarify_when_multiple_businesses_in_session() -> None:
    turns = [_turn(1, "Prior", "Prior", "Ans", "Business|B1", ["Business|B1", "Business|B2"])]
    d = resolve_question_with_session_memory("What about the business?", turns)
    assert d.action == "clarify"


def test_followup_line_anchors_single_business() -> None:
    turns = [_turn(1, "Prior", "Prior", "Ans", "Business|BX", ["Business|BX"])]
    d = resolve_question_with_session_memory(
        "Also map business relationships for fraud indicators", turns
    )
    assert d.action == "rewrite"
    assert "Business|BX" in d.resolved_question


def test_rewrite_that_address_single_in_session() -> None:
    turns = [_turn(1, "Prior", "Prior", "Ans", "address_9002", ["address_9002", "Person|1"])]
    d = resolve_question_with_session_memory("Who lives at that address?", turns)
    assert d.action == "rewrite"
    assert "address_9002" in d.resolved_question


def test_rewrite_there_locative_single_address() -> None:
    turns = [_turn(1, "Prior", "Prior", "Ans", "address_9002", ["address_9002"])]
    d = resolve_question_with_session_memory("What policies are linked there?", turns)
    assert d.action == "rewrite"
    assert "address_9002" in d.resolved_question


def test_clarify_when_multiple_addresses_in_session() -> None:
    turns = [_turn(1, "Prior", "Prior", "Ans", "address_9002", ["address_9002", "address_9035"])]
    d = resolve_question_with_session_memory("Who lives there?", turns)
    assert d.action == "clarify"

