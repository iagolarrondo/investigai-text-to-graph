from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.session.context_resolver import resolve_question_with_session_memory  # noqa: E402
from src.llm.tool_agent import ToolAgentResult  # noqa: E402
from src.session.memory import build_turn_from_result, merge_session_referents  # noqa: E402
from src.session.node_id_canonical import (  # noqa: E402
    canonicalize_id_list,
    canonicalize_referents_dict,
    resolve_node_id_to_graph,
)
from src.session.report import build_session_report_html  # noqa: E402


def _graph_person_snake_only() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("person_5063", node_type="Person", label="Test", properties_json="{}")
    return G


def test_resolve_pipe_person_to_snake_when_only_snake_in_graph() -> None:
    G = _graph_person_snake_only()
    assert resolve_node_id_to_graph("Person|5063", G) == "person_5063"
    assert resolve_node_id_to_graph("person_5063", G) == "person_5063"


def test_canonicalize_id_list_dedupes_pipe_and_snake() -> None:
    G = _graph_person_snake_only()
    out = canonicalize_id_list(["Person|5063", "person_5063", "Person|5063"], G)
    assert out == ["person_5063"]


def test_canonicalize_referents_drops_invalid_pipe_when_not_in_graph() -> None:
    G = _graph_person_snake_only()
    refs = {"primary_person": "Person|9999", "primary_claim": None}
    assert canonicalize_referents_dict(refs, G) == {}


def test_merge_session_referents_prefers_graph_native_id() -> None:
    G = _graph_person_snake_only()
    with patch("src.graph_query.query_graph.get_graph", return_value=G):
        out = merge_session_referents({"primary_person": "Person|5063"}, {})
        assert out.get("primary_person") == "person_5063"


def test_merge_skips_invalid_update_and_keeps_prior_canonical() -> None:
    G = _graph_person_snake_only()
    with patch("src.graph_query.query_graph.get_graph", return_value=G):
        out = merge_session_referents(
            {"primary_person": "person_5063"},
            {"primary_person": "Person|9999"},
        )
    assert out.get("primary_person") == "person_5063"


def test_follow_up_he_rewrites_to_snake_person_id() -> None:
    G = _graph_person_snake_only()
    turns = [
        {
            "turn_id": 1,
            "created_at_utc": "2026-01-01T00:00:00+00:00",
            "user_question": "Who is Jane?",
            "investigation_question": "Who is person_5063?",
            "final_answer": "x",
            "graph_focus_node_id": "person_5063",
            "anchors": ["person_5063"],
            "reviewer_notes": [],
            "synthesis_rationale": "",
            "active_referents": {"primary_person": "person_5063", "graph_focus": "person_5063"},
            "answer_summary_bullets": [],
        }
    ]
    with patch("src.graph_query.query_graph.get_graph", return_value=G):
        d = resolve_question_with_session_memory(
            "What policies did he hold?",
            turns,
            session_referents={"primary_person": "Person|5063"},
        )
    assert d.action == "rewrite"
    assert "person_5063" in d.resolved_question
    assert "Person|5063" not in d.resolved_question


def test_html_report_key_entities_dedupe_mixed_person_formats() -> None:
    G = _graph_person_snake_only()
    html = ""
    with patch("src.graph_query.query_graph.get_graph", return_value=G):
        html = build_session_report_html(
            [
                {
                    "turn_id": 1,
                    "user_question": "Q",
                    "investigation_question": "Q",
                    "final_answer": "A",
                    "graph_focus_node_id": "person_5063",
                    "anchors": ["Person|5063", "person_5063"],
                    "reviewer_notes": [],
                    "active_referents": {},
                    "answer_summary_bullets": ["b1"],
                }
            ]
        )
    assert html.count("person_5063") >= 1
    assert html.count("Person|5063") == 0


def test_build_turn_from_result_stores_single_graph_native_person_id() -> None:
    G = _graph_person_snake_only()
    tr = ToolAgentResult(
        question="q",
        steps=[],
        final_text="Answer",
        graph_focus_node_id="Person|5063",
    )
    with patch("src.graph_query.query_graph.get_graph", return_value=G):
        with patch(
            "src.session.memory.gather_investigation_anchors",
            return_value={"Person|5063", "person_5063"},
        ):
            turn = build_turn_from_result(
                turn_id=1,
                user_question="Who is Jane?",
                investigation_question="Who is person_5063?",
                result=tr,
            )
    assert turn.anchors == ["person_5063"]
    assert turn.graph_focus_node_id == "person_5063"
    assert turn.active_referents.get("primary_person") == "person_5063"
