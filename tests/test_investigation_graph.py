"""Tests for investigation summary subgraph anchor extraction."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.investigation_graph import (  # noqa: E402
    extract_node_ids_from_text,
    gather_investigation_anchors,
    infer_summary_view_mode,
)
from src.llm.tool_agent import ToolAgentResult, ToolAgentStep  # noqa: E402


def test_extract_node_ids_from_text_basic() -> None:
    s = "Focus on Person|1004 and Claim|C001; Policy|POL002."
    ids = extract_node_ids_from_text(s)
    assert "Person|1004" in ids
    assert "Claim|C001" in ids
    assert "Policy|POL002" in ids


def test_gather_investigation_anchors_merges_input_and_text() -> None:
    tr = ToolAgentResult(
        question="q",
        steps=[
            ToolAgentStep(
                tool="get_person_policies",
                input={"person_node_id": "1004"},
                result_preview="Matches:\nPerson|1004  Person",
            ),
        ],
        final_text="Also Policy|POL001.",
    )
    anchors = gather_investigation_anchors(tr)
    assert "Person|1004" in anchors
    assert "Policy|POL001" in anchors


def test_infer_summary_view_mode_tools() -> None:
    tr_p2p = ToolAgentResult(
        question="Map clusters",
        steps=[ToolAgentStep(tool="find_related_people_clusters", input={}, result_preview="")],
        final_text="",
    )
    assert infer_summary_view_mode(tr_p2p) == "p2p"

    tr_claim = ToolAgentResult(
        question="Who on the policy",
        steps=[ToolAgentStep(tool="get_claim_network", input={"claim_node_id": "Claim|C001"}, result_preview="")],
        final_text="",
    )
    assert infer_summary_view_mode(tr_claim) == "claims_policies"

    tr_bank = ToolAgentResult(
        question="Joint accounts",
        steps=[ToolAgentStep(tool="find_shared_bank_accounts", input={}, result_preview="")],
        final_text="",
    )
    assert infer_summary_view_mode(tr_bank) == "financial"


def test_infer_summary_view_mode_question_p2p() -> None:
    tr = ToolAgentResult(
        question="What is the relationship between these two people?",
        steps=[ToolAgentStep(tool="search_nodes", input={"query": "Jane"}, result_preview="")],
        final_text="",
    )
    assert infer_summary_view_mode(tr) == "p2p"


def test_gather_investigation_anchors_neighbor_tool() -> None:
    tr = ToolAgentResult(
        question="q",
        steps=[
            ToolAgentStep(
                tool="get_neighbors",
                input={"node_id": "Business|2001"},
                result_preview="{}",
            ),
        ],
        final_text="",
    )
    anchors = gather_investigation_anchors(tr)
    assert "Business|2001" in anchors
