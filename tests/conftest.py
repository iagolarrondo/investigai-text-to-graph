"""Isolate tests from a developer shell that exports ``GRAPH_BACKEND=neo4j``."""

import pytest


@pytest.fixture(autouse=True)
def _default_graph_backend_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRAPH_BACKEND", raising=False)
    monkeypatch.delenv("NEO4J_READ_MODE", raising=False)
