from __future__ import annotations

from src.session.report import build_session_report_html


def test_build_session_report_html_contains_turn_data() -> None:
    html = build_session_report_html(
        [
            {
                "turn_id": 1,
                "user_question": "Who is Person|1004?",
                "investigation_question": "Who is Person|1004?",
                "final_answer": "Answer",
                "graph_focus_node_id": "Person|1004",
                "anchors": ["Person|1004"],
                "reviewer_notes": [],
            }
        ]
    )
    assert "InvestigAI Session Report" in html
    assert "Who is Person|1004?" in html
    assert "Person|1004" in html

