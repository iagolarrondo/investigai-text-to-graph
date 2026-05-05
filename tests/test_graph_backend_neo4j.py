"""GRAPH_BACKEND toggle and optional CSV vs Neo4j summary parity."""

from __future__ import annotations

import os

import pytest

from src.graph_query.neo4j_nx_loader import neo4j_graph_backend_enabled


def test_neo4j_backend_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GRAPH_BACKEND", raising=False)
    assert neo4j_graph_backend_enabled() is False


@pytest.mark.parametrize(
    "value",
    ["neo4j", "NEO4J", "aura", "1", "true", "yes"],
)
def test_neo4j_backend_enabled_values(monkeypatch, value: str):
    monkeypatch.setenv("GRAPH_BACKEND", value)
    assert neo4j_graph_backend_enabled() is True


def test_csv_vs_neo4j_summarize_graph_parity(monkeypatch):
    """Compare node/edge counts and type histograms when Aura mirrors processed CSVs."""
    pytest.importorskip("neo4j")

    from src.project_env import load_project_dotenv

    load_project_dotenv()
    if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
        pytest.skip("NEO4J_URI / NEO4J_PASSWORD not set (after loading .env.example)")

    from src.graph_query import query_graph as qg

    project_root = qg.PROJECT_ROOT
    nodes_csv = project_root / "data" / "processed" / "nodes.csv"
    edges_csv = project_root / "data" / "processed" / "edges.csv"
    if not nodes_csv.is_file() or not edges_csv.is_file():
        pytest.skip("processed CSVs missing")

    monkeypatch.delenv("GRAPH_BACKEND", raising=False)
    qg._graph = None
    qg.load_graph()
    summary_csv = qg.summarize_graph()

    monkeypatch.setenv("GRAPH_BACKEND", "neo4j")
    qg._graph = None
    qg.load_graph()
    summary_neo = qg.summarize_graph()

    assert summary_neo["num_nodes"] == summary_csv["num_nodes"]
    assert summary_neo["num_edges"] == summary_csv["num_edges"]
    assert summary_neo["node_types"] == summary_csv["node_types"]
    assert summary_neo["edge_types"] == summary_csv["edge_types"]
