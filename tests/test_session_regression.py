from __future__ import annotations

import pytest

from src.session.context_resolver import resolve_question_with_session_memory
from src.session.memory import merge_session_referents
from src.session.report import build_session_report_html, summarize_answer_bullets


def _turn(
    turn_id: int,
    user_q: str,
    inv_q: str,
    answer: str,
    focus: str | None,
    anchors: list[str],
    *,
    active_referents: dict | None = None,
    bullets: list[str] | None = None,
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
        "active_referents": active_referents or {},
        "answer_summary_bullets": bullets or [],
    }


def test_export_html_lists_turn_immediately_after_list_append_like_streamlit_order() -> None:
    """Regression: report must include a turn as soon as it exists in session_turns (same 'rerun')."""
    turns: list[dict] = []
    turns.append(
        _turn(
            1,
            "Who is Person|1004?",
            "Who is Person|1004?",
            "Long narrative " * 40,
            "Person|1004",
            ["Person|1004"],
            bullets=["First finding", "Second finding"],
        )
    )
    html = build_session_report_html(turns)
    assert "Turn 1" in html
    assert "First finding" in html
    assert "<ul class='tight'>" in html
    assert "Full answer (detail)" in html


def test_pronoun_follow_up_uses_session_referent_overlay() -> None:
    t1 = _turn(
        1,
        "Tell me about the subject",
        "Tell me about Person|1004",
        "Summary",
        "Person|1004",
        ["Person|1004", "Claim|C1"],
        active_referents={
            "primary_person": "Person|1004",
            "primary_claim": "Claim|C1",
            "graph_focus": "Person|1004",
        },
    )
    merged = merge_session_referents({}, t1["active_referents"])
    d = resolve_question_with_session_memory(
        "What policies did he hold?",
        [t1],
        session_referents=merged,
    )
    assert d.action == "rewrite"
    assert "Person|1004" in d.resolved_question
    d2 = resolve_question_with_session_memory(
        "Did he share a bank account with anyone?",
        [t1],
        session_referents=merged,
    )
    assert d2.action == "rewrite"
    assert "Person|1004" in d2.resolved_question


def test_unresolved_pronoun_clarifies_without_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_MEMORY_LLM_REWRITE", "0")
    t1 = _turn(
        1,
        "Bank question",
        "Show bank_8013",
        "No person in focus.",
        "bank_8013",
        ["bank_8013"],
        active_referents={"primary_bank": "bank_8013", "graph_focus": "bank_8013"},
    )
    merged = merge_session_referents({}, t1["active_referents"])
    d = resolve_question_with_session_memory(
        "What did he do next?",
        [t1],
        session_referents=merged,
    )
    assert d.action == "clarify"
    assert "graph entity" in d.clarification_prompt.lower() or "entity" in d.clarification_prompt.lower()


def test_summarize_answer_bullets_prefers_markdown_list() -> None:
    text = "### Key findings\n- Alpha.\n- Beta.\n- Gamma.\n"
    b = summarize_answer_bullets(text, max_bullets=5)
    assert "Alpha" in b[0]
    assert len(b) >= 2
