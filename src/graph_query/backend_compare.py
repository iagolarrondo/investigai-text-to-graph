"""
Compare **CSV → NetworkX** vs **Neo4j → NetworkX** for the same ``query_graph`` calls.

Both backends produce an ``nx.DiGraph`` with identical attributes; this script loads each
graph separately, swaps ``query_graph._graph`` while running named probes, and reports match/mismatch.

Examples::

    PYTHONPATH=. python -m src.graph_query.backend_compare --list
    PYTHONPATH=. python -m src.graph_query.backend_compare summarize catalog
    PYTHONPATH=. python -m src.graph_query.backend_compare claim_network --claim-id claim_C9000000001
    PYTHONPATH=. python -m src.graph_query.backend_compare search_nodes --search-q Wilson
    PYTHONPATH=. python -m src.graph_query.backend_compare summarize --timing

**Streamlit:** multipage app → *Backend comparison — probes* (``src/app/pages/2_Backend_Comparison.py``).

**Adding probes:** append a name and a ``lambda ns: ...`` entry to ``QUERY_RUNNERS`` below
(``ns`` is :class:`argparse.Namespace` with ``claim_id``, ``max_depth``, ``search_q``, etc.).
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from difflib import unified_diff
from typing import Any

import networkx as nx
import pandas as pd

from src.graph_query.neo4j_nx_loader import fetch_di_graph_from_neo4j
from src.graph_query import query_graph as qg


@contextmanager
def temporary_graph(G):
    """Point ``query_graph._graph`` at *G* for the duration of the block."""
    prev = qg._graph
    qg._graph = G
    try:
        yield
    finally:
        qg._graph = prev


def normalize_for_compare(obj: Any) -> Any:
    """Turn API results into JSON-stable structures for equality / diff."""
    if obj is None:
        return None
    if isinstance(obj, pd.DataFrame):
        if obj.empty:
            return []
        cols = sorted(obj.columns)
        df = obj[cols].fillna(pd.NA)
        df = df.sort_values(by=list(cols)).reset_index(drop=True)
        records = []
        for row in df.to_dict(orient="records"):
            records.append({str(k): normalize_for_compare(v) for k, v in sorted(row.items())})
        return records
    if isinstance(obj, pd.Series):
        return normalize_for_compare(obj.to_dict())
    if isinstance(obj, dict):
        return {
            str(k): normalize_for_compare(v)
            for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(obj, (list, tuple)):
        return [normalize_for_compare(x) for x in obj]
    if isinstance(obj, float) and pd.isna(obj):
        return None
    if hasattr(obj, "item") and callable(getattr(obj, "item", None)):
        try:
            return normalize_for_compare(obj.item())
        except Exception:
            pass
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def canonical_lines(obj: Any) -> list[str]:
    return json.dumps(normalize_for_compare(obj), indent=2, sort_keys=True).splitlines()


def diff_summary(
    left: Any,
    right: Any,
    label: str,
    *,
    fromfile: str = "csv",
    tofile: str = "neo4j",
) -> tuple[bool, str]:
    a = canonical_lines(left)
    b = canonical_lines(right)
    if a == b:
        return True, f"{label}: MATCH"
    diff_lines = list(unified_diff(a, b, fromfile=fromfile, tofile=tofile, lineterm=""))
    cap = 200
    body = "\n".join(diff_lines[:cap])
    if len(diff_lines) > cap:
        body += "\n... (truncated)"
    return False, f"{label}: MISMATCH\n{body}"


@dataclass(frozen=True)
class QuerySpec:
    """Runner receives :class:`argparse.Namespace` (claim_id, search_q, …)."""

    runner: Callable[[argparse.Namespace], Any]
    needs_claim_id: bool = False
    needs_search_q: bool = False


@dataclass(frozen=True)
class ProbeTimingRow:
    name: str
    accurate: bool
    query_csv_ms: float
    query_neo_ms: float
    mismatch_detail: str | None
    norm_csv: Any | None = None  # normalized JSON-stable payloads for UI
    norm_neo: Any | None = None


@dataclass(frozen=True)
class ComparisonBatchResult:
    hydrate_csv_ms: float | None
    hydrate_neo_ms: float | None
    nodes_csv: int
    edges_csv: int
    nodes_neo: int
    edges_neo: int
    probes: tuple[ProbeTimingRow, ...]
    graphs: tuple[nx.DiGraph, nx.DiGraph]


def _run_summarize(_ns: argparse.Namespace) -> Any:
    return qg.summarize_graph()


def _run_catalog(_ns: argparse.Namespace) -> Any:
    return qg.get_graph_relationship_catalog()


def _run_claim_network(ns: argparse.Namespace) -> Any:
    return qg.get_claim_network(ns.claim_id.strip())


def _run_claim_subgraph(ns: argparse.Namespace) -> Any:
    return qg.get_claim_subgraph_summary(ns.claim_id.strip(), max_depth=int(ns.max_depth))


def _run_search_nodes(ns: argparse.Namespace) -> Any:
    nt = (ns.node_type or "").strip() or None
    return qg.search_nodes(ns.search_q.strip(), node_type=nt, limit=int(ns.search_limit))


def _run_shared_banks(_ns: argparse.Namespace) -> Any:
    return qg.find_shared_bank_accounts()


def _run_people_clusters(_ns: argparse.Namespace) -> Any:
    return qg.find_related_people_clusters()


def _run_business_patterns(_ns: argparse.Namespace) -> Any:
    return qg.find_business_connection_patterns()


QUERY_RUNNERS: dict[str, QuerySpec] = {
    "summarize": QuerySpec(_run_summarize),
    "catalog": QuerySpec(_run_catalog),
    "claim_network": QuerySpec(_run_claim_network, needs_claim_id=True),
    "claim_subgraph": QuerySpec(_run_claim_subgraph, needs_claim_id=True),
    "search_nodes": QuerySpec(_run_search_nodes, needs_search_q=True),
    "shared_banks": QuerySpec(_run_shared_banks),
    "people_clusters": QuerySpec(_run_people_clusters),
    "business_patterns": QuerySpec(_run_business_patterns),
}


def probe_arg_errors(name: str, ns: argparse.Namespace) -> str | None:
    if name not in QUERY_RUNNERS:
        return f"Unknown probe `{name}`."
    spec = QUERY_RUNNERS[name]
    cid = (getattr(ns, "claim_id", None) or "").strip()
    if spec.needs_claim_id and not cid:
        return f"Probe `{name}` requires a claim id."
    sq = (getattr(ns, "search_q", None) or "").strip()
    if spec.needs_search_q and not sq:
        return f"Probe `{name}` requires a search string."
    return None


def _validate_args(name: str, ns: argparse.Namespace) -> None:
    err = probe_arg_errors(name, ns)
    if err:
        raise SystemExit(err)


def _exec_probe(G: nx.DiGraph, name: str, ns: argparse.Namespace) -> Any:
    with temporary_graph(G):
        return QUERY_RUNNERS[name].runner(ns)


def run_query_on_graph(G: nx.DiGraph, name: str, ns: argparse.Namespace) -> Any:
    err = probe_arg_errors(name, ns)
    if err:
        raise SystemExit(err)
    return _exec_probe(G, name, ns)


def load_graph_pair() -> tuple[nx.DiGraph, nx.DiGraph]:
    """Load CSV graph and Neo4j-hydrated graph (raises on missing CSV or Neo4j failure)."""
    G_csv = qg._load_graph_from_csv_files()
    G_neo = fetch_di_graph_from_neo4j()
    return G_csv, G_neo


def run_comparison_batch(
    names: list[str],
    ns: argparse.Namespace,
    *,
    cached_graphs: tuple[nx.DiGraph, nx.DiGraph] | None = None,
    store_normalized_payloads: bool = False,
) -> ComparisonBatchResult:
    """
    Run probes on CSV vs Neo4j graphs with timings.

    ``cached_graphs`` — optional ``(G_csv, G_neo)`` to skip hydration (hydrate ms reported as ``None``).
    ``store_normalized_payloads`` — attach ``norm_csv`` / ``norm_neo`` per probe for Streamlit diff viewers.
    """
    for name in names:
        err = probe_arg_errors(name, ns)
        if err:
            raise ValueError(err)

    prev = qg._graph
    try:
        hydrate_csv_ms: float | None
        hydrate_neo_ms: float | None
        if cached_graphs is not None:
            G_csv, G_neo = cached_graphs
            hydrate_csv_ms = None
            hydrate_neo_ms = None
        else:
            t0 = time.perf_counter()
            G_csv = qg._load_graph_from_csv_files()
            hydrate_csv_ms = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            G_neo = fetch_di_graph_from_neo4j()
            hydrate_neo_ms = (time.perf_counter() - t0) * 1000

        probes: list[ProbeTimingRow] = []
        for name in names:
            t0 = time.perf_counter()
            left = _exec_probe(G_csv, name, ns)
            query_csv_ms = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            right = _exec_probe(G_neo, name, ns)
            query_neo_ms = (time.perf_counter() - t0) * 1000

            ok, msg = diff_summary(left, right, name)
            nc = normalize_for_compare(left) if store_normalized_payloads else None
            nn = normalize_for_compare(right) if store_normalized_payloads else None
            probes.append(
                ProbeTimingRow(
                    name=name,
                    accurate=ok,
                    query_csv_ms=query_csv_ms,
                    query_neo_ms=query_neo_ms,
                    mismatch_detail=None if ok else msg,
                    norm_csv=nc,
                    norm_neo=nn,
                )
            )

        return ComparisonBatchResult(
            hydrate_csv_ms=hydrate_csv_ms,
            hydrate_neo_ms=hydrate_neo_ms,
            nodes_csv=G_csv.number_of_nodes(),
            edges_csv=G_csv.number_of_edges(),
            nodes_neo=G_neo.number_of_nodes(),
            edges_neo=G_neo.number_of_edges(),
            probes=tuple(probes),
            graphs=(G_csv, G_neo),
        )
    finally:
        qg._graph = prev


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Run query_graph probes against CSV vs Neo4j-backed graphs side-by-side.",
    )
    p.add_argument(
        "queries",
        nargs="*",
        help=f"Probe names (default: summarize). Known: {', '.join(sorted(QUERY_RUNNERS))}",
    )
    p.add_argument("--list", action="store_true", help="Print probe names and exit.")
    p.add_argument("--claim-id", default="", help="claim_network / claim_subgraph anchor.")
    p.add_argument("--max-depth", type=int, default=2, help="claim_subgraph max_depth.")
    p.add_argument("--search-q", default="", help="search_nodes substring.")
    p.add_argument("--node-type", default="", help="Optional search_nodes filter.")
    p.add_argument("--search-limit", type=int, default=40, help="search_nodes limit.")
    p.add_argument("--json", action="store_true", help="Emit normalized JSON for both backends.")
    p.add_argument(
        "--timing",
        action="store_true",
        help="Also print per-probe query timings (CSV vs Neo4j ms). Hydrate timings always print.",
    )
    ns = p.parse_args(argv)

    if ns.list:
        for k in sorted(QUERY_RUNNERS):
            print(k)
        return 0

    names = ns.queries or ["summarize"]
    unknown = [x for x in names if x not in QUERY_RUNNERS]
    if unknown:
        raise SystemExit(f"Unknown probe(s): {unknown}. Use --list.")

    if ns.json:
        print("Loading CSV graph …")
        try:
            G_csv = qg._load_graph_from_csv_files()
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc

        print("Loading Neo4j graph …")
        try:
            G_neo = fetch_di_graph_from_neo4j()
        except Exception as exc:
            raise SystemExit(
                "Neo4j load failed. Check NEO4J_* in .env.example and run sync_processed.\n"
                f"Detail: {exc}"
            ) from exc

        print(
            f"CSV: {G_csv.number_of_nodes()} nodes, {G_csv.number_of_edges()} edges | "
            f"Neo4j: {G_neo.number_of_nodes()} nodes, {G_neo.number_of_edges()} edges\n"
        )

        prev_global = qg._graph
        try:
            for name in names:
                _validate_args(name, ns)
                left = _exec_probe(G_csv, name, ns)
                right = _exec_probe(G_neo, name, ns)
                print(f"=== {name} (csv) ===")
                print(json.dumps(normalize_for_compare(left), indent=2, sort_keys=True))
                print(f"=== {name} (neo4j) ===")
                print(json.dumps(normalize_for_compare(right), indent=2, sort_keys=True))
        finally:
            qg._graph = prev_global
        return 0

    try:
        batch = run_comparison_batch(names, ns)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    except Exception as exc:
        raise SystemExit(
            "Neo4j load failed. Check NEO4J_* in .env.example and run sync_processed.\n"
            f"Detail: {exc}"
        ) from exc

    print(
        f"CSV: {batch.nodes_csv} nodes, {batch.edges_csv} edges | "
        f"Neo4j: {batch.nodes_neo} nodes, {batch.edges_neo} edges"
    )
    if batch.hydrate_csv_ms is not None and batch.hydrate_neo_ms is not None:
        ratio = (
            batch.hydrate_neo_ms / batch.hydrate_csv_ms
            if batch.hydrate_csv_ms > 0
            else float("nan")
        )
        print(
            f"Hydrate: CSV {batch.hydrate_csv_ms:,.1f} ms | Neo4j {batch.hydrate_neo_ms:,.1f} ms "
            f"(Neo4j / CSV × {ratio:.2f})\n"
        )
    else:
        print("Hydrate: (cached graphs — timings omitted)\n")

    any_fail = False
    for row in batch.probes:
        if ns.timing:
            slower = "Neo4j" if row.query_neo_ms > row.query_csv_ms else "CSV"
            print(
                f"  [{row.name}] query CSV {row.query_csv_ms:,.2f} ms | "
                f"Neo4j {row.query_neo_ms:,.2f} ms (slower: {slower})"
            )
        if row.accurate:
            print(f"{row.name}: MATCH\n")
        else:
            assert row.mismatch_detail is not None
            print(row.mismatch_detail + "\n")
            any_fail = True

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
