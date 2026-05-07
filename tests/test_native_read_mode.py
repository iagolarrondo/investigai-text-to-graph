"""``NEO4J_READ_MODE`` toggle (no live Aura required)."""

from __future__ import annotations

import pytest

from src.graph_query.native_read_mode import (
    NATIVE_READ_TOOLS,
    neo4j_llm_cypher_reads_enabled,
    neo4j_native_reads_enabled,
)


def test_native_reads_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_READ_MODE", raising=False)
    assert neo4j_native_reads_enabled() is False


@pytest.mark.parametrize("v", ["native", "cypher", "1", "true", "yes"])
def test_native_reads_on(monkeypatch: pytest.MonkeyPatch, v: str) -> None:
    monkeypatch.setenv("NEO4J_READ_MODE", v)
    assert neo4j_native_reads_enabled() is True


@pytest.mark.parametrize("v", ["llm_cypher", "llm-cypher", "llm-authored", "llm"])
def test_llm_cypher_mode(monkeypatch: pytest.MonkeyPatch, v: str) -> None:
    monkeypatch.setenv("NEO4J_READ_MODE", v)
    assert neo4j_llm_cypher_reads_enabled() is True
    assert neo4j_native_reads_enabled() is False


def test_llm_cypher_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_READ_MODE", raising=False)
    assert neo4j_llm_cypher_reads_enabled() is False


def test_native_not_triggered_by_llm_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_READ_MODE", "llm_cypher")
    assert neo4j_native_reads_enabled() is False
