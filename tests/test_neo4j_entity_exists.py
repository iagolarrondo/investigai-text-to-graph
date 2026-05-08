"""Unit tests for ``neo4j_native_reads.entity_exists`` (no live Neo4j required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_entity_exists_empty_id() -> None:
    from src.graph_query import neo4j_native_reads as nnr

    assert nnr.entity_exists("") is False
    assert nnr.entity_exists("   ") is False


def test_entity_exists_delegates_to_run_read_query(monkeypatch) -> None:
    from src.graph_query import neo4j_native_reads as nnr

    seen: list[tuple[str, dict]] = []

    def fake_run_read_query(cypher: str, params: dict) -> list:
        seen.append((cypher, dict(params)))
        if params.get("id") == "Person|1":
            return [{"ok": 1}]
        return []

    monkeypatch.setattr(nnr, "run_read_query", fake_run_read_query)
    assert nnr.entity_exists("Person|1") is True
    assert nnr.entity_exists("missing") is False
    assert len(seen) == 2
