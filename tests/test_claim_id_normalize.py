"""Tests for fuzzy claim node id normalization (``Claim 005`` → ``Claim|C005``)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.tool_agent import (  # noqa: E402
    claim_node_id_candidates,
    normalize_claim_node_id,
)


def test_claim_node_id_candidates_space_form() -> None:
    c = claim_node_id_candidates("Claim 005")
    assert "Claim|C005" in c


def test_claim_node_id_candidates_builder_prefix() -> None:
    c = claim_node_id_candidates("claim_C005")
    assert "Claim|C005" in c


def test_normalize_claim_node_id_resolves_against_graph() -> None:
    G = nx.DiGraph()
    G.add_node("Claim|C005", node_type="Claim", label="L")
    G.add_node("Person|1001", node_type="Person", label="P")
    with patch("src.llm.tool_agent.qg.get_graph", return_value=G):
        assert normalize_claim_node_id("Claim 005") == "Claim|C005"
        assert normalize_claim_node_id("claim_C005") == "Claim|C005"
        assert normalize_claim_node_id("Claim|C005") == "Claim|C005"


def test_normalize_claim_prefers_first_existing_node() -> None:
    G = nx.DiGraph()
    G.add_node("Claim|C005", node_type="Claim", label="L")
    with patch("src.llm.tool_agent.qg.get_graph", return_value=G):
        assert normalize_claim_node_id("005") == "Claim|C005"
