"""
Normalize rows from ``data/processed/nodes.csv`` and ``edges.csv``.

Schemas match ``src/graph_query/query_graph.load_graph`` (original CSV + Neo4j-export columns).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_NODES = PROJECT_ROOT / "data" / "processed" / "nodes.csv"
DEFAULT_EDGES = PROJECT_ROOT / "data" / "processed" / "edges.csv"


def _parse_properties_json(raw: Any) -> dict[str, Any]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return {}


def iter_normalized_nodes(nodes_csv: Path) -> list[dict[str, Any]]:
    df = pd.read_csv(nodes_csv)
    neo4j_nodes = "id" in df.columns and "node_id" not in df.columns
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        if neo4j_nodes:
            node_id = str(row["id"])
            node_type = str(row.get("labels", "Unknown"))
            props = _parse_properties_json(row.get("properties_json"))
            label = (
                props.get("NAME")
                or props.get("name")
                or props.get("POLICY_NUMBER")
                or props.get("CLAIM_ID")
                or props.get("ADDRESS")
                or props.get("ACCOUNT_NUMBER")
                or node_id
            )
            out.append(
                {
                    "node_id": node_id,
                    "node_type": node_type,
                    "label": str(label),
                    "source_table": "",
                    "properties_json": str(row.get("properties_json", "{}")),
                }
            )
        else:
            out.append(
                {
                    "node_id": str(row["node_id"]),
                    "node_type": str(row["node_type"]),
                    "label": str(row["label"]),
                    "source_table": str(row.get("source_table", "") or ""),
                    "properties_json": str(row.get("properties_json", "{}")),
                }
            )
    return out


def iter_normalized_edges(edges_csv: Path) -> list[dict[str, Any]]:
    df = pd.read_csv(edges_csv)
    neo4j_edges = "start_id" in df.columns and "source_node_id" not in df.columns
    out: list[dict[str, Any]] = []
    for i, row in df.iterrows():
        if neo4j_edges:
            out.append(
                {
                    "edge_id": f"e_{int(i):06d}",
                    "source_node_id": str(row["start_id"]),
                    "target_node_id": str(row["end_id"]),
                    "edge_type": str(row.get("relationship_type", "") or ""),
                    "source_table": "",
                    "properties_json": str(row.get("properties_json", "{}")),
                }
            )
        else:
            eid = row.get("edge_id", f"e_{int(i):06d}")
            out.append(
                {
                    "edge_id": str(eid),
                    "source_node_id": str(row["source_node_id"]),
                    "target_node_id": str(row["target_node_id"]),
                    "edge_type": str(row.get("edge_type", "") or ""),
                    "source_table": str(row.get("source_table", "") or ""),
                    "properties_json": str(row.get("properties_json", "{}")),
                }
            )
    return out
