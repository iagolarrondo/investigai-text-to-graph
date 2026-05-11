"""Neo4j CSV sync: offline dry-run always; live tests only when NEO4J_* env is set."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.graph_store.processed_csv import DEFAULT_EDGES, DEFAULT_NODES
from src.graph_store.sync_processed import sync_processed_csv


def test_sync_processed_dry_run_counts():
    stats = sync_processed_csv(
        DEFAULT_NODES,
        DEFAULT_EDGES,
        clear=False,
        batch_size=500,
        dry_run=True,
    )
    assert stats["nodes"] >= 1
    assert stats["edges_loaded"] >= 1
    assert stats["edges_loaded"] <= stats["edges_total"]


@pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="NEO4J_URI not set — skip Aura connectivity check.")
def test_neo4j_verify_connectivity():
    from src.graph_store.neo4j_client import verify_connectivity

    verify_connectivity()


def _delete_pytest_entities(driver, database: str | None) -> None:
    """Remove only nodes prefixed ``__pytest_`` so we never wipe a user's full graph."""
    with driver.session(**({"database": database} if database else {})) as session:
        session.run(
            "MATCH (n:Entity) WHERE n.node_id STARTS WITH $pfx DETACH DELETE n",
            pfx="__pytest_",
        )


@pytest.mark.skipif(
    not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"),
    reason="NEO4J_URI / NEO4J_PASSWORD not set — skip live sync.",
)
def test_neo4j_sync_tiny_roundtrip_counts(tmp_path: Path):
    """MERGE three nodes + one edge under ``__pytest_*`` ids; does not ``MATCH (n) DELETE`` the DB."""
    from neo4j.exceptions import ClientError

    from src.graph_store.neo4j_client import neo4j_database, open_driver

    nodes = tmp_path / "nodes.csv"
    edges = tmp_path / "edges.csv"
    nodes.write_text(
        "node_id,node_type,label,source_table,properties_json\n"
        '__pytest_p1,Person,Alice,"",{}\n'
        '__pytest_p2,Person,Bob,"",{}\n'
        '__pytest_a1,Address,"123 Main","","{}"\n',
        encoding="utf-8",
    )
    edges.write_text(
        "edge_id,source_node_id,target_node_id,edge_type,source_table,properties_json\n"
        '__pytest_e1,__pytest_p1,__pytest_a1,LOCATED_IN,"",{}\n',
        encoding="utf-8",
    )

    driver = open_driver()
    db = neo4j_database()
    try:
        try:
            _delete_pytest_entities(driver, db)
        except ClientError as exc:
            msg = str(exc).lower()
            code = getattr(exc, "code", "") or ""
            if "databasenotfound" in code.lower() or "not found" in msg or "does not exist" in msg:
                pytest.skip(f"Neo4j database not available for sync test: {exc}")
            raise
        stats = sync_processed_csv(nodes, edges, clear=False, batch_size=50, dry_run=False)
        assert stats["nodes"] == 3
        assert stats["edges_loaded"] == 1

        with driver.session(**({"database": db} if db else {})) as session:
            one = session.run(
                "MATCH (p:Entity {node_id: '__pytest_p1'})-[r:GRAPH_EDGE]->(a:Entity {node_id: '__pytest_a1'}) "
                "RETURN r.edge_type AS t"
            ).single()
            assert one is not None and one["t"] == "LOCATED_IN"
    finally:
        try:
            _delete_pytest_entities(driver, db)
        except ClientError:
            pass
        driver.close()
