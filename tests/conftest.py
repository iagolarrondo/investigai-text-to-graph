"""Isolate tests from a developer shell that exports ``GRAPH_BACKEND=neo4j``."""

import pytest


@pytest.fixture(autouse=True)
def _default_graph_backend_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("NEO4J_READ_MODE", raising=False)


@pytest.fixture(autouse=True)
def _clear_query_graph_between_tests() -> None:
    """Avoid session-memory tests seeing a graph loaded by an earlier test module."""
    import src.graph_query.query_graph as qg

    qg._graph = None
    yield
    qg._graph = None
