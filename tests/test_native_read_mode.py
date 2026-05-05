"""``NEO4J_READ_MODE`` toggle (no live Aura required)."""

from __future__ import annotations

import pytest

from src.graph_query.native_read_mode import (
    NATIVE_READ_TOOLS,
    neo4j_native_reads_enabled,
)


def test_native_reads_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_READ_MODE", raising=False)
    assert neo4j_native_reads_enabled() is False


@pytest.mark.parametrize("v", ["native", "cypher", "1", "true", "yes"])
def test_native_reads_on(monkeypatch: pytest.MonkeyPatch, v: str) -> None:
    monkeypatch.setenv("NEO4J_READ_MODE", v)
    assert neo4j_native_reads_enabled() is True


def test_native_tool_registry_nonempty() -> None:
    assert "summarize_graph" in NATIVE_READ_TOOLS
    assert "search_nodes" in NATIVE_READ_TOOLS
