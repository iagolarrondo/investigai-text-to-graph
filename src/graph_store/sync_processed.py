"""
Load processed CSV graph into Neo4j for experiments.

Data model (generic, works without APOC):

- Nodes: ``(:Entity {node_id, node_type, label, source_table, properties_json})``
- Edges: ``(:Entity)-[:GRAPH_EDGE {edge_id, edge_type, source_table, properties_json}]->(:Entity)``

Real ``edge_type`` / ``node_type`` stay as properties so existing domain strings are preserved.

Usage (from repo root)::

    pip install neo4j python-dotenv pandas
    # Put NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in ``.env`` (see ``env.template``).
    python -m src.graph_store.sync_processed --clear

Optional: ``--dry-run`` to print counts only; ``--batch-size 500`` for tuning.

Try in **Neo4j Browser** after sync::

    MATCH (n:Entity) RETURN count(n) AS entities;
    MATCH ()-[r:GRAPH_EDGE]->() RETURN count(r) AS links;
    MATCH (n:Entity {node_type: 'Person'}) RETURN n.node_id, n.label LIMIT 25;
    MATCH (a:Entity)-[r:GRAPH_EDGE {edge_type: 'LOCATED_IN'}]->(b:Entity)
    RETURN a.node_id, b.node_id LIMIT 25;
"""

from __future__ import annotations

import argparse
from pathlib import Path

from neo4j import Driver
from neo4j.exceptions import ClientError

from src.graph_store.neo4j_client import neo4j_database, open_driver
from src.graph_store.processed_csv import (
    DEFAULT_EDGES,
    DEFAULT_NODES,
    iter_normalized_edges,
    iter_normalized_nodes,
)

_ENSURE_CONSTRAINTS = """
CREATE CONSTRAINT entity_node_id_unique IF NOT EXISTS
FOR (n:Entity) REQUIRE n.node_id IS UNIQUE
"""

_CREATE_NODE_TYPE_INDEX = """
CREATE INDEX entity_node_type_idx IF NOT EXISTS FOR (n:Entity) ON (n.node_type)
"""

_CREATE_EDGE_TYPE_INDEX = """
CREATE INDEX graph_edge_type_idx IF NOT EXISTS FOR ()-[r:GRAPH_EDGE]-() ON (r.edge_type)
"""

_DELETE_ALL = "MATCH (n) DETACH DELETE n"

_UNWIND_MERGE_NODES = """
UNWIND $batch AS row
MERGE (n:Entity {node_id: row.node_id})
SET n.node_type = row.node_type,
    n.label = row.label,
    n.source_table = row.source_table,
    n.properties_json = row.properties_json
"""

_UNWIND_MERGE_EDGES = """
UNWIND $batch AS row
MATCH (a:Entity {node_id: row.source_node_id})
MATCH (b:Entity {node_id: row.target_node_id})
MERGE (a)-[r:GRAPH_EDGE {edge_id: row.edge_id}]->(b)
SET r.edge_type = row.edge_type,
    r.source_table = row.source_table,
    r.properties_json = row.properties_json
"""


def _ensure_schema(driver: Driver, database: str | None) -> None:
    def work(tx):
        tx.run(_ENSURE_CONSTRAINTS)
        tx.run(_CREATE_NODE_TYPE_INDEX)

    with driver.session(database=database) as session:
        session.execute_write(work)

    def rel_index(tx):
        tx.run(_CREATE_EDGE_TYPE_INDEX)

    try:
        with driver.session(database=database) as session:
            session.execute_write(rel_index)
    except ClientError:
        # Relationship property indexes require newer Neo4j; sync still works without this.
        pass


def _clear_graph(driver: Driver, database: str | None) -> None:
    with driver.session(database=database) as session:
        session.execute_write(lambda tx: tx.run(_DELETE_ALL))


def _write_batches(
    driver: Driver,
    database: str | None,
    cypher: str,
    batches: list[list[dict]],
) -> None:
    def run_batch(tx, batch: list[dict], cy: str = cypher):
        tx.run(cy, batch=batch)

    with driver.session(database=database) as session:
        for batch in batches:
            session.execute_write(run_batch, batch)


def _chunked(rows: list[dict], size: int) -> list[list[dict]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def sync_processed_csv(
    nodes_csv: Path,
    edges_csv: Path,
    *,
    clear: bool,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    nodes = iter_normalized_nodes(nodes_csv)
    edges = iter_normalized_edges(edges_csv)
    node_ids = {n["node_id"] for n in nodes}
    skipped = 0
    kept: list[dict] = []
    for e in edges:
        if e["source_node_id"] in node_ids and e["target_node_id"] in node_ids:
            kept.append(e)
        else:
            skipped += 1

    if dry_run:
        return {
            "nodes": len(nodes),
            "edges_total": len(edges),
            "edges_loaded": len(kept),
            "edges_skipped_orphans": skipped,
        }

    driver = open_driver()
    db = neo4j_database()
    try:
        _ensure_schema(driver, db)
        if clear:
            _clear_graph(driver, db)
        _write_batches(driver, db, _UNWIND_MERGE_NODES, _chunked(nodes, batch_size))
        _write_batches(driver, db, _UNWIND_MERGE_EDGES, _chunked(kept, batch_size))
    finally:
        driver.close()

    return {
        "nodes": len(nodes),
        "edges_total": len(edges),
        "edges_loaded": len(kept),
        "edges_skipped_orphans": skipped,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Sync data/processed CSVs into Neo4j.")
    p.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    p.add_argument("--edges", type=Path, default=DEFAULT_EDGES)
    p.add_argument(
        "--clear",
        action="store_true",
        help="Delete all nodes/relationships before load (recommended for a clean experiment).",
    )
    p.add_argument("--batch-size", type=int, default=800)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.nodes.is_file() or not args.edges.is_file():
        raise SystemExit(f"Missing CSV: {args.nodes} or {args.edges}")

    stats = sync_processed_csv(
        args.nodes,
        args.edges,
        clear=args.clear,
        batch_size=max(1, args.batch_size),
        dry_run=args.dry_run,
    )
    print(stats)
    if args.dry_run:
        print("Dry run only — no writes.")
    elif not args.clear:
        print("Note: loaded with MERGE (--clear not set); stale nodes/edges may remain.")


if __name__ == "__main__":
    main()
