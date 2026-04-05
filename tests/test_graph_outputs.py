"""
Smoke tests for the **exported graph CSVs** (`data/processed/nodes.csv`, `edges.csv`).

These files are produced by::

    python src/graph_build/build_graph_files.py

Run tests **from the project root** (the folder that contains `src/` and `data/`)::

    pytest tests/test_graph_outputs.py -v

If a test fails, read the assertion message — it usually means the graph was not
built yet, or the pipeline dropped a node/edge type we expect for PoC v1.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

# This file lives in tests/ → project root is one level up
PROJECT_ROOT = Path(__file__).resolve().parent.parent
NODES_CSV = PROJECT_ROOT / "data" / "processed" / "nodes.csv"
EDGES_CSV = PROJECT_ROOT / "data" / "processed" / "edges.csv"

# Minimum vocabulary for the current synthetic PoC (see query_graph demos / seed data)
KEY_NODE_TYPES = frozenset(
    {"Person", "Claim", "Policy", "Address", "BankAccount", "Business"}
)
KEY_EDGE_TYPES = frozenset(
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


def test_nodes_csv_exists_and_is_not_empty() -> None:
    """The nodes file must exist and contain at least one data row (plus header)."""
    assert NODES_CSV.is_file(), (
        f"Missing {NODES_CSV}. Build the graph first:\n"
        f"  python src/graph_build/build_graph_files.py"
    )
    df = pd.read_csv(NODES_CSV)
    assert not df.empty, "nodes.csv has headers but no rows — check the build script."


def test_edges_csv_exists_and_is_not_empty() -> None:
    """Every edge list should have at least one relationship."""
    assert EDGES_CSV.is_file(), (
        f"Missing {EDGES_CSV}. Build the graph first:\n"
        f"  python src/graph_build/build_graph_files.py"
    )
    df = pd.read_csv(EDGES_CSV)
    assert not df.empty, "edges.csv has headers but no rows — check the build script."


def test_all_edge_endpoints_exist_in_nodes() -> None:
    """
    Referential sanity check: edges must only point at node ids that exist.

    If this fails, the builder may be emitting orphan edges or mis-typed ids.
    """
    nodes_df = pd.read_csv(NODES_CSV)
    edges_df = pd.read_csv(EDGES_CSV)
    node_ids = set(nodes_df["node_id"].dropna().astype(str))

    for col in ("source_node_id", "target_node_id"):
        assert col in edges_df.columns, f"edges.csv is missing required column {col!r}"
        endpoints = set(edges_df[col].dropna().astype(str))
        unknown = endpoints - node_ids
        assert not unknown, (
            f"{len(unknown)} edge endpoint(s) in {col!r} are not in nodes.csv "
            f"(showing up to 15): {sorted(unknown)[:15]}"
        )


def test_key_node_types_are_present() -> None:
    """PoC queries assume these node kinds exist in the export."""
    df = pd.read_csv(NODES_CSV)
    assert "node_type" in df.columns, "nodes.csv must have a node_type column"
    present = set(df["node_type"].dropna().unique())
    missing = KEY_NODE_TYPES - present
    assert not missing, f"Expected node types missing from graph: {sorted(missing)}"


def test_key_edge_types_are_present() -> None:
    """PoC investigation helpers rely on these relationship types."""
    df = pd.read_csv(EDGES_CSV)
    assert "edge_type" in df.columns, "edges.csv must have an edge_type column"
    present = set(df["edge_type"].dropna().unique())
    missing = KEY_EDGE_TYPES - present
    assert not missing, f"Expected edge types missing from graph: {sorted(missing)}"
