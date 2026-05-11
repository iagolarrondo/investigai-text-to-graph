"""
Hydrate a :class:`networkx.DiGraph` from Neo4j using the same model as ``sync_processed``:

- Nodes ``(:Entity {node_id, node_type, label, source_table, properties_json})``
- Edges ``[:GRAPH_EDGE {edge_id, edge_type, source_table, properties_json}]``

This keeps **all** ``query_graph`` helpers and LLM extensions unchanged while Neo4j is the source of truth.
"""

from __future__ import annotations

import json
import os

import networkx as nx


def _properties_json_as_str(val) -> str:
    if val is None:
        return "{}"
    if isinstance(val, dict):
        return json.dumps(val)
    return str(val)


def neo4j_graph_backend_enabled() -> bool:
    v = (os.getenv("GRAPH_BACKEND") or "").strip().lower()
    return v in ("neo4j", "aura", "1", "true", "yes")


def fetch_di_graph_from_neo4j() -> nx.DiGraph:
    from src.graph_store.neo4j_client import neo4j_database, open_driver

    G = nx.DiGraph()
    driver = open_driver()
    db = neo4j_database()

    q_nodes = """
    MATCH (n:Entity)
    RETURN n.node_id AS node_id,
           coalesce(n.node_type, '') AS node_type,
           coalesce(n.label, '') AS label,
           coalesce(n.source_table, '') AS source_table,
           coalesce(n.properties_json, '{}') AS properties_json
    """

    q_edges = """
    MATCH (a:Entity)-[r:GRAPH_EDGE]->(b:Entity)
    RETURN coalesce(r.edge_id, '') AS edge_id,
           a.node_id AS source_node_id,
           b.node_id AS target_node_id,
           coalesce(r.edge_type, '') AS edge_type,
           coalesce(r.source_table, '') AS source_table,
           coalesce(r.properties_json, '{}') AS properties_json
    """

    try:
        with driver.session(**({"database": db} if db else {})) as session:
            for row in session.run(q_nodes):
                nid = row["node_id"]
                if nid is None:
                    continue
                G.add_node(
                    str(nid),
                    node_type=str(row["node_type"] or ""),
                    label=str(row["label"] or ""),
                    source_table=str(row["source_table"] or ""),
                    properties_json=_properties_json_as_str(row["properties_json"]),
                )
            for row in session.run(q_edges):
                u, v = row["source_node_id"], row["target_node_id"]
                if u is None or v is None:
                    continue
                G.add_edge(
                    str(u),
                    str(v),
                    edge_id=str(row["edge_id"] or ""),
                    edge_type=str(row["edge_type"] or ""),
                    source_table=str(row["source_table"] or ""),
                    properties_json=_properties_json_as_str(row["properties_json"]),
                )
    finally:
        driver.close()

    return G
