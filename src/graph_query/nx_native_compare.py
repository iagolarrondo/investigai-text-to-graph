"""
Compare **NetworkX graph scans** vs **Neo4j Cypher** for the same logical tools.

Loads one CSV-backed ``nx.DiGraph``, runs each probe with ``force_networkx_reads()`` so
``query_graph`` walks memory, then runs the matching ``neo4j_native_reads`` /
``neo4j_native_heavy`` implementation against Aura.

CLI hydration comparison stays in :mod:`src.graph_query.backend_compare`; Streamlit can offer both modes.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import networkx as nx

from src.graph_query import neo4j_native_heavy as nnh
from src.graph_query import neo4j_native_reads as nnr
from src.graph_query import query_graph as qg
from src.graph_query.backend_compare import diff_summary, normalize_for_compare, temporary_graph
from src.graph_query.native_read_mode import force_networkx_reads


@dataclass(frozen=True)
class NxNativeSpec:
    nx_runner: Callable[[argparse.Namespace], Any]
    native_runner: Callable[[argparse.Namespace], Any]
    needs_claim_id: bool = False
    needs_search_q: bool = False
    needs_person_id: bool = False
    needs_policy_id: bool = False
    needs_neighbor_id: bool = False


def _summarize_nx(_ns: argparse.Namespace) -> Any:
    return qg.summarize_graph()


def _summarize_nat(_ns: argparse.Namespace) -> Any:
    return nnr.summarize_graph()


def _catalog_nx(_ns: argparse.Namespace) -> Any:
    return qg.get_graph_relationship_catalog()


def _catalog_nat(_ns: argparse.Namespace) -> Any:
    return nnr.get_graph_relationship_catalog()


def _claim_network_nx(ns: argparse.Namespace) -> Any:
    return qg.get_claim_network(ns.claim_id.strip())


def _claim_network_nat(ns: argparse.Namespace) -> Any:
    return nnh.get_claim_network(ns.claim_id.strip())


def _claim_subgraph_nx(ns: argparse.Namespace) -> Any:
    return qg.get_claim_subgraph_summary(ns.claim_id.strip(), max_depth=int(ns.max_depth))


def _claim_subgraph_nat(ns: argparse.Namespace) -> Any:
    return nnh.get_claim_subgraph_summary(ns.claim_id.strip(), max_depth=int(ns.max_depth))


def _person_subgraph_nx(ns: argparse.Namespace) -> Any:
    return qg.get_person_subgraph_summary(ns.person_id.strip(), max_depth=int(ns.max_depth))


def _person_subgraph_nat(ns: argparse.Namespace) -> Any:
    return nnh.get_person_subgraph_summary(ns.person_id.strip(), max_depth=int(ns.max_depth))


def _policy_network_nx(ns: argparse.Namespace) -> Any:
    return qg.get_policy_network(ns.policy_id.strip())


def _policy_network_nat(ns: argparse.Namespace) -> Any:
    return nnh.get_policy_network(ns.policy_id.strip())


def _search_nodes_nx(ns: argparse.Namespace) -> Any:
    nt = (ns.node_type or "").strip() or None
    return qg.search_nodes(ns.search_q.strip(), node_type=nt, limit=int(ns.search_limit))


def _search_nodes_nat(ns: argparse.Namespace) -> Any:
    nt = (ns.node_type or "").strip() or None
    return nnr.search_nodes(ns.search_q.strip(), node_type=nt, limit=int(ns.search_limit))


def _neighbors_nx(ns: argparse.Namespace) -> Any:
    return qg.get_neighbors(ns.neighbor_node_id.strip())


def _neighbors_nat(ns: argparse.Namespace) -> Any:
    return nnr.get_neighbors(ns.neighbor_node_id.strip())


def _person_policies_nx(ns: argparse.Namespace) -> Any:
    return qg.get_person_policies(ns.person_id.strip())


def _person_policies_nat(ns: argparse.Namespace) -> Any:
    return nnr.get_person_policies(ns.person_id.strip())


def _policies_coparties_nx(ns: argparse.Namespace) -> Any:
    return qg.policies_with_related_coparties(ns.person_id.strip())


def _policies_coparties_nat(ns: argparse.Namespace) -> Any:
    return nnh.policies_with_related_coparties(ns.person_id.strip())


def _shared_banks_nx(_ns: argparse.Namespace) -> Any:
    return qg.find_shared_bank_accounts()


def _shared_banks_nat(_ns: argparse.Namespace) -> Any:
    return nnh.find_shared_bank_accounts()


def _people_clusters_nx(_ns: argparse.Namespace) -> Any:
    return qg.find_related_people_clusters()


def _people_clusters_nat(_ns: argparse.Namespace) -> Any:
    return nnh.find_related_people_clusters()


def _business_patterns_nx(_ns: argparse.Namespace) -> Any:
    return qg.find_business_connection_patterns()


def _business_patterns_nat(_ns: argparse.Namespace) -> Any:
    return nnh.find_business_connection_patterns()


NX_NATIVE_QUERY_RUNNERS: dict[str, NxNativeSpec] = {
    "summarize": NxNativeSpec(_summarize_nx, _summarize_nat),
    "catalog": NxNativeSpec(_catalog_nx, _catalog_nat),
    "claim_network": NxNativeSpec(_claim_network_nx, _claim_network_nat, needs_claim_id=True),
    "claim_subgraph": NxNativeSpec(_claim_subgraph_nx, _claim_subgraph_nat, needs_claim_id=True),
    "person_subgraph": NxNativeSpec(_person_subgraph_nx, _person_subgraph_nat, needs_person_id=True),
    "policy_network": NxNativeSpec(_policy_network_nx, _policy_network_nat, needs_policy_id=True),
    "search_nodes": NxNativeSpec(_search_nodes_nx, _search_nodes_nat, needs_search_q=True),
    "neighbors": NxNativeSpec(_neighbors_nx, _neighbors_nat, needs_neighbor_id=True),
    "person_policies": NxNativeSpec(_person_policies_nx, _person_policies_nat, needs_person_id=True),
    "policies_coparties": NxNativeSpec(_policies_coparties_nx, _policies_coparties_nat, needs_person_id=True),
    "shared_banks": NxNativeSpec(_shared_banks_nx, _shared_banks_nat),
    "people_clusters": NxNativeSpec(_people_clusters_nx, _people_clusters_nat),
    "business_patterns": NxNativeSpec(_business_patterns_nx, _business_patterns_nat),
}


@dataclass(frozen=True)
class NxNativeProbeTimingRow:
    name: str
    accurate: bool
    query_nx_ms: float
    query_native_ms: float
    mismatch_detail: str | None
    norm_nx: Any | None = None
    norm_native: Any | None = None


@dataclass(frozen=True)
class NxNativeComparisonBatchResult:
    hydrate_csv_ms: float | None
    nodes_csv: int
    edges_csv: int
    probes: tuple[NxNativeProbeTimingRow, ...]
    graph: nx.DiGraph


def nx_native_probe_arg_errors(name: str, ns: argparse.Namespace) -> str | None:
    if name not in NX_NATIVE_QUERY_RUNNERS:
        return f"Unknown probe `{name}`."
    spec = NX_NATIVE_QUERY_RUNNERS[name]
    if spec.needs_claim_id and not (getattr(ns, "claim_id", None) or "").strip():
        return f"Probe `{name}` requires a claim id."
    if spec.needs_search_q and not (getattr(ns, "search_q", None) or "").strip():
        return f"Probe `{name}` requires a search string."
    if spec.needs_person_id and not (getattr(ns, "person_id", None) or "").strip():
        return f"Probe `{name}` requires a person id."
    if spec.needs_policy_id and not (getattr(ns, "policy_id", None) or "").strip():
        return f"Probe `{name}` requires a policy id."
    if spec.needs_neighbor_id and not (getattr(ns, "neighbor_node_id", None) or "").strip():
        return f"Probe `{name}` requires a neighbor anchor node id."
    return None


def _exec_nx_probe(G: nx.DiGraph, name: str, ns: argparse.Namespace) -> Any:
    spec = NX_NATIVE_QUERY_RUNNERS[name]
    with temporary_graph(G), force_networkx_reads():
        return spec.nx_runner(ns)


def _exec_native_probe(name: str, ns: argparse.Namespace) -> Any:
    return NX_NATIVE_QUERY_RUNNERS[name].native_runner(ns)


def run_nx_vs_native_batch(
    names: list[str],
    ns: argparse.Namespace,
    *,
    cached_graph: nx.DiGraph | None = None,
    store_normalized_payloads: bool = False,
) -> NxNativeComparisonBatchResult:
    for name in names:
        err = nx_native_probe_arg_errors(name, ns)
        if err:
            raise ValueError(err)

    prev = qg._graph
    try:
        if cached_graph is not None:
            G_csv = cached_graph
            hydrate_csv_ms = None
        else:
            t0 = time.perf_counter()
            G_csv = qg._load_graph_from_csv_files()
            hydrate_csv_ms = (time.perf_counter() - t0) * 1000

        probes: list[NxNativeProbeTimingRow] = []
        for name in names:
            t0 = time.perf_counter()
            left = _exec_nx_probe(G_csv, name, ns)
            nx_ms = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            right = _exec_native_probe(name, ns)
            native_ms = (time.perf_counter() - t0) * 1000

            ok, msg = diff_summary(left, right, name, fromfile="nx_scan", tofile="cypher")
            nx_norm = normalize_for_compare(left) if store_normalized_payloads else None
            nat_norm = normalize_for_compare(right) if store_normalized_payloads else None
            probes.append(
                NxNativeProbeTimingRow(
                    name=name,
                    accurate=ok,
                    query_nx_ms=nx_ms,
                    query_native_ms=native_ms,
                    mismatch_detail=None if ok else msg,
                    norm_nx=nx_norm,
                    norm_native=nat_norm,
                )
            )

        return NxNativeComparisonBatchResult(
            hydrate_csv_ms=hydrate_csv_ms,
            nodes_csv=G_csv.number_of_nodes(),
            edges_csv=G_csv.number_of_edges(),
            probes=tuple(probes),
            graph=G_csv,
        )
    finally:
        qg._graph = prev
