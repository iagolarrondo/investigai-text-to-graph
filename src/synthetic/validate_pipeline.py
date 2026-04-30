from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.graph_query import query_graph as qg

NODES_CSV = PROJECT_ROOT / "data" / "processed" / "nodes.csv"
EDGES_CSV = PROJECT_ROOT / "data" / "processed" / "edges.csv"


def _assert_no_label_leakage(seed_dir: Path) -> None:
    forbidden = ("scenario", "suspicious", "ground_truth", "eval", "label")
    for csv_path in sorted(seed_dir.glob("*.csv")):
        df = pd.read_csv(csv_path, nrows=5)
        cols = [c.lower() for c in df.columns]
        leaked = [c for c in cols if any(tok in c for tok in forbidden)]
        if leaked:
            raise AssertionError(f"Operational seed has hidden-label-like columns in {csv_path.name}: {leaked}")


def _assert_graph_endpoints_valid() -> None:
    nodes = pd.read_csv(NODES_CSV)
    edges = pd.read_csv(EDGES_CSV)
    node_ids = set(nodes["node_id"].astype(str))
    for col in ("source_node_id", "target_node_id"):
        unknown = set(edges[col].astype(str)) - node_ids
        if unknown:
            preview = sorted(unknown)[:10]
            raise AssertionError(f"{col} contains endpoints not in nodes.csv: {preview}")


def _assert_queries_surface_patterns() -> None:
    qg.load_graph()
    shared = qg.find_shared_bank_accounts()["table"]
    biz = qg.find_business_connection_patterns()["table"]
    clusters = qg.find_related_people_clusters()["table"]
    if shared.empty:
        raise AssertionError("Expected at least one shared bank account case.")
    if biz.empty:
        raise AssertionError("Expected at least one business/person colocation case.")
    if clusters.empty:
        raise AssertionError("Expected at least one related people cluster.")


def _assert_ambiguous_eval_cases(eval_dir: Path) -> None:
    registry = pd.read_csv(eval_dir / "scenario_registry.csv")
    if "ambiguous" not in set(registry["suspiciousness"].astype(str).str.lower()):
        raise AssertionError("No ambiguous scenarios found in eval registry.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate generated synthetic dataset and graph outputs.")
    parser.add_argument("--seed-dir", required=True, help="Operational seed directory used for build_graph_files.")
    parser.add_argument("--eval-dir", required=True, help="Hidden eval metadata directory.")
    parser.add_argument(
        "--run-build",
        action="store_true",
        help="Rebuild data/processed/nodes.csv and edges.csv from the supplied seed directory first.",
    )
    args = parser.parse_args()

    seed_dir = Path(args.seed_dir).resolve()
    eval_dir = Path(args.eval_dir).resolve()

    if args.run_build:
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "src" / "graph_build" / "build_graph_files.py"),
                "--seed-dir",
                str(seed_dir),
            ],
            check=True,
            cwd=str(PROJECT_ROOT),
        )

    _assert_no_label_leakage(seed_dir)
    _assert_graph_endpoints_valid()
    _assert_queries_surface_patterns()
    _assert_ambiguous_eval_cases(eval_dir)
    print("Validation passed: operational seed integrity, graph consistency, query coverage, and hidden eval separation.")


if __name__ == "__main__":
    main()

