"""
Smoke tests for the **exported graph CSVs** (`data/processed/nodes.csv`, `edges.csv`).

Supports two on-disk shapes:

- **Builder schema** (from ``build_graph_files.py``): ``node_id``, ``node_type``,
  ``source_node_id``, ``target_node_id``, ``edge_type``.
- **Neo4j export schema**: ``id``, ``labels``, ``start_id``, ``end_id``,
  ``relationship_type`` (loaded the same way in ``query_graph.load_graph``).

Run from the project root::

    pytest tests/test_graph_outputs.py -v

If a test fails, build or refresh the graph CSVs first::

    python src/graph_build/build_graph_files.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NODES_CSV = PROJECT_ROOT / "data" / "processed" / "nodes.csv"
EDGES_CSV = PROJECT_ROOT / "data" / "processed" / "edges.csv"

GraphSchema = Literal["builder", "neo4j"]

# PoC investigation code in ``query_graph`` expects these node kinds to exist.
KEY_NODE_TYPES = frozenset(
    {"Person", "Claim", "Policy", "Address", "BankAccount", "Business"}
)

# Builder-export relationship names (Person→Bank uses HOLD_BY).
KEY_EDGE_TYPES_BUILDER = frozenset(
    {
        "LOCATED_IN",
        "HOLD_BY",
        "IS_CLAIM_AGAINST_POLICY",
        "IS_COVERED_BY",
        "SOLD_POLICY",
        "IS_SPOUSE_OF",
        "IS_RELATED_TO",
    }
)

# Neo4j-style exports often use HELD_BY (direction may differ from builder); same logical coverage.
KEY_EDGE_TYPES_NEO4J = frozenset(
    {
        "LOCATED_IN",
        "HELD_BY",
        "IS_CLAIM_AGAINST_POLICY",
        "IS_COVERED_BY",
        "SOLD_POLICY",
        "IS_SPOUSE_OF",
        "IS_RELATED_TO",
    }
)


def _detect_schema(nodes_df: pd.DataFrame, edges_df: pd.DataFrame) -> GraphSchema:
    has_builder = (
        "node_id" in nodes_df.columns
        and "source_node_id" in edges_df.columns
        and "target_node_id" in edges_df.columns
    )
    has_neo4j = "id" in nodes_df.columns and "start_id" in edges_df.columns and "end_id" in edges_df.columns
    if has_builder:
        return "builder"
    if has_neo4j:
        return "neo4j"
    pytest.fail(
        "Unrecognized graph CSV schema: expected builder columns "
        "(node_id / source_node_id / target_node_id) or Neo4j export "
        "(id / start_id / end_id)."
    )


def _node_type_values(nodes_df: pd.DataFrame, schema: GraphSchema) -> set[str]:
    if schema == "builder":
        assert "node_type" in nodes_df.columns, "builder nodes.csv must have node_type"
        return set(nodes_df["node_type"].dropna().astype(str).unique())
    assert "labels" in nodes_df.columns, "Neo4j nodes.csv must have labels"
    out: set[str] = set()
    for raw in nodes_df["labels"].dropna().astype(str):
        # Single label per row in typical exports; tolerate "A|B" if ever used
        for part in raw.replace("|", ",").split(","):
            p = part.strip()
            if p:
                out.add(p)
    return out


def _edge_type_values(edges_df: pd.DataFrame, schema: GraphSchema) -> set[str]:
    col = "edge_type" if schema == "builder" else "relationship_type"
    assert col in edges_df.columns, f"edges.csv must have {col!r}"
    return set(edges_df[col].dropna().astype(str).unique())


def test_nodes_csv_exists_and_is_not_empty() -> None:
    assert NODES_CSV.is_file(), (
        f"Missing {NODES_CSV}. Build the graph first:\n"
        f"  python src/graph_build/build_graph_files.py"
    )
    df = pd.read_csv(NODES_CSV)
    assert not df.empty, "nodes.csv has headers but no rows — check the build script."


def test_edges_csv_exists_and_is_not_empty() -> None:
    assert EDGES_CSV.is_file(), (
        f"Missing {EDGES_CSV}. Build the graph first:\n"
        f"  python src/graph_build/build_graph_files.py"
    )
    df = pd.read_csv(EDGES_CSV)
    assert not df.empty, "edges.csv has headers but no rows — check the build script."


def test_all_edge_endpoints_exist_in_nodes() -> None:
    """Every edge endpoint id must appear in the node id column for that schema."""
    nodes_df = pd.read_csv(NODES_CSV)
    edges_df = pd.read_csv(EDGES_CSV)
    schema = _detect_schema(nodes_df, edges_df)

    if schema == "builder":
        node_ids = set(nodes_df["node_id"].dropna().astype(str))
        endpoint_cols = ("source_node_id", "target_node_id")
    else:
        node_ids = set(nodes_df["id"].dropna().astype(str))
        endpoint_cols = ("start_id", "end_id")

    for col in endpoint_cols:
        assert col in edges_df.columns, f"edges.csv is missing required column {col!r}"
        endpoints = set(edges_df[col].dropna().astype(str))
        unknown = endpoints - node_ids
        assert not unknown, (
            f"{len(unknown)} edge endpoint(s) in {col!r} are not in nodes.csv "
            f"(showing up to 15): {sorted(unknown)[:15]}"
        )


def test_key_node_types_are_present() -> None:
    """PoC queries assume these node kinds exist (as node_type or Neo4j labels)."""
    nodes_df = pd.read_csv(NODES_CSV)
    edges_df = pd.read_csv(EDGES_CSV)
    schema = _detect_schema(nodes_df, edges_df)
    present = _node_type_values(nodes_df, schema)
    missing = KEY_NODE_TYPES - present
    assert not missing, f"Expected node types missing from graph: {sorted(missing)} (schema={schema})"


def test_key_edge_types_are_present() -> None:
    """PoC investigation helpers rely on these relationship names for the active schema."""
    nodes_df = pd.read_csv(NODES_CSV)
    edges_df = pd.read_csv(EDGES_CSV)
    schema = _detect_schema(nodes_df, edges_df)
    present = _edge_type_values(edges_df, schema)
    required = KEY_EDGE_TYPES_BUILDER if schema == "builder" else KEY_EDGE_TYPES_NEO4J
    missing = required - present
    assert not missing, (
        f"Expected edge types missing from graph: {sorted(missing)} (schema={schema})"
    )


def test_relationship_catalog_sums_to_edge_count() -> None:
    """Introspection catalog aggregates every edge exactly once."""
    from src.graph_query import query_graph as qg

    qg.load_graph()
    G = qg.get_graph()
    cat = qg.get_graph_relationship_catalog()
    tbl = cat["table"]
    assert int(tbl["count"].sum()) == G.number_of_edges()
    assert {"from_node_type", "edge_type", "to_node_type", "count"}.issubset(set(tbl.columns))
