"""Unit tests for ``backend_compare`` normalization (no Neo4j required)."""

from __future__ import annotations

import networkx as nx
import pandas as pd
import pytest

from src.graph_query.backend_compare import (
    canonical_lines,
    normalize_for_compare,
    temporary_graph,
)
from src.graph_query import query_graph as qg


def test_normalize_dataframe_sorts_rows():
    df1 = pd.DataFrame([{"b": 2, "a": 1}, {"b": 1, "a": 3}])
    df2 = pd.DataFrame([{"a": 3, "b": 1}, {"a": 1, "b": 2}])
    assert normalize_for_compare(df1) == normalize_for_compare(df2)


def test_canonical_lines_identical_nested():
    left = {"x": pd.DataFrame([{"id": 1}]), "y": 2}
    right = {"y": 2, "x": pd.DataFrame([{"id": 1}])}
    assert canonical_lines(left) == canonical_lines(right)


def test_temporary_graph_restores_global():
    G = nx.DiGraph()
    G.add_node(
        "n1",
        node_type="Person",
        label="Test",
        source_table="",
        properties_json="{}",
    )
    prev = qg._graph
    try:
        with temporary_graph(G):
            assert qg.get_graph() is G
        assert qg._graph is prev
    finally:
        qg._graph = prev


def test_main_list_returns_zero():
    from src.graph_query.backend_compare import main

    assert main(["--list"]) == 0


def test_main_unknown_query_exit():
    from src.graph_query.backend_compare import main

    with pytest.raises(SystemExit):
        main(["not_a_probe"])
