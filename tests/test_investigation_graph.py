"""Tests for investigation summary subgraph anchor extraction and hop-ego view."""

from __future__ import annotations

import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.investigation_graph import (  # noqa: E402
    compute_hop_ego_visible,
    compute_summary_visible_nodes,
    extract_node_ids_from_text,
    gather_investigation_anchors,
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


def test_compute_hop_ego_visible_includes_neighbors() -> None:
    G = nx.DiGraph()
    G.add_node("Person|1", node_type="Person", label="A", properties_json="{}")
    G.add_node("Claim|C1", node_type="Claim", label="C", properties_json="{}")
    G.add_edge("Person|1", "Claim|C1", edge_type="X")
    vis = compute_hop_ego_visible(G, "Person|1", hop_depth=2, max_nodes=50)
    assert "Person|1" in vis
    assert "Claim|C1" in vis


def test_compute_summary_visible_nodes_uses_synthesis_focus() -> None:
    G = nx.DiGraph()
    G.add_node("Person|1", node_type="Person", label="A", properties_json="{}")
    G.add_node("Claim|C1", node_type="Claim", label="C", properties_json="{}")
    G.add_edge("Person|1", "Claim|C1", edge_type="X")
    tr = ToolAgentResult(
        question="q",
        steps=[
            ToolAgentStep(tool="search_nodes", input={"query": "x"}, result_preview="Person|1"),
        ],
        final_text="",
        graph_focus_node_id="Claim|C1",
    )
    anchors = gather_investigation_anchors(tr)
    vis, focus, mode, edge_f, cap = compute_summary_visible_nodes(G, tr, anchors, hop_depth=2)
    assert mode == "hop_ego"
    assert focus == "Claim|C1"
    assert "Claim|C1" in vis
    assert "Person|1" in vis
    assert edge_f is None
    assert cap and "Claim|C1" in cap


def test_gather_investigation_anchors_includes_raw_synthesis_focus() -> None:
    tr = ToolAgentResult(
        question="q",
        steps=[],
        final_text="",
        graph_focus_node_id="address_9001",
    )
    anchors = gather_investigation_anchors(tr)
    assert anchors == {"address_9001"}


def test_compute_summary_visible_nodes_raw_graph_focus_id() -> None:
    G = nx.DiGraph()
    G.add_node("address_9001", node_type="Address", label="9001 Main", properties_json="{}")
    G.add_node("person_5001", node_type="Person", label="A", properties_json="{}")
    G.add_edge("person_5001", "address_9001", edge_type="LOCATED_IN")
    tr = ToolAgentResult(
        question="q",
        steps=[],
        final_text="",
        graph_focus_node_id="address_9001",
    )
    anchors = gather_investigation_anchors(tr)
    vis, focus, mode, edge_f, cap = compute_summary_visible_nodes(G, tr, anchors, hop_depth=1)
    assert focus == "address_9001"
    assert "address_9001" in vis
    assert "person_5001" in vis
    assert edge_f is None


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
