"""Parameterized read queries against Aura (no bulk graph hydrate).

Uses a persistent module-level driver (``get_driver``) so the connection pool stays warm
between calls — avoids a fresh TLS handshake on every query.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from src.graph_store.neo4j_client import get_driver, neo4j_session_kwargs


def run_read_query(cypher: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a single read Cypher statement; return rows as dicts."""
    driver = get_driver()
    with driver.session(**neo4j_session_kwargs()) as session:
        result = session.run(cypher, dict(params or {}))
        return [dict(r) for r in result]


def run_read_transaction(work: Callable[[Any], Any]) -> Any:
    """Run ``work(tx)`` inside ``session.execute_read`` (``tx`` is a managed read transaction)."""
    driver = get_driver()
    with driver.session(**neo4j_session_kwargs()) as session:
        return session.execute_read(work)
