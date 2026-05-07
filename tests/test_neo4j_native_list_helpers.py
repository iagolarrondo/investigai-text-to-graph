"""Neo4j native list helpers (no live database)."""

from __future__ import annotations

import pytest

import src.graph_query.neo4j_native_reads as nnr


def test_list_node_ids_by_type_empty_type(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("run_read_query should not be called")

    monkeypatch.setattr(nnr, "run_read_query", boom)
    assert nnr.list_node_ids_by_type("  ") == []


def test_list_node_ids_by_type_queries_nt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake(cypher: str, params: dict | None = None) -> list:
        captured["cypher"] = cypher
        captured["params"] = params
        return [{"id": "P|1"}, {"id": "P|2"}]

    monkeypatch.setattr(nnr, "run_read_query", fake)
    out = nnr.list_node_ids_by_type("Person")
    assert out == ["P|1", "P|2"]
    assert captured["params"] == {"nt": "Person"}


def test_list_edge_rows_by_type_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(_cypher: str, _params: dict | None = None) -> list:
        return [
            {
                "source": "a",
                "target": "b",
                "edge_id": "e1",
                "edge_type": "X",
                "source_table": "t",
                "properties_json": "{}",
            }
        ]

    monkeypatch.setattr(nnr, "run_read_query", fake)
    rows = nnr.list_edge_rows_by_type("X")
    assert len(rows) == 1
    assert rows[0]["source"] == "a" and rows[0]["target"] == "b"
