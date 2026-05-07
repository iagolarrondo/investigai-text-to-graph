"""
Run the **full investigation** (tool planner → judge → synthesis) twice for backend comparison.

- **Hydrate:** same question on ``CSV → NetworkX`` vs ``Neo4j → NetworkX`` (both paths scan in-memory graphs).
- **NX vs Cypher:** same question on ``CSV`` graph with ``force_networkx_reads()`` vs the same graph with
  ``NEO4J_READ_MODE=native`` (ported tools hit Aura).

LLM calls are **non-deterministic**; traces may differ even when graph answers match. Use ``final_text``
and tool payloads as the main comparison signal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import networkx as nx

from src.graph_query import query_graph as qg
from src.graph_query.backend_compare import diff_summary, normalize_for_compare, temporary_graph
from src.graph_query.native_read_mode import force_networkx_reads, temporary_neo4j_read_native
from src.graph_query.neo4j_nx_loader import fetch_di_graph_from_neo4j
from src.llm.tool_agent import ToolAgentResult, run_tool_planner_agent


def tool_agent_result_for_compare(tr: ToolAgentResult) -> dict[str, Any]:
    steps = [
        {
            "tool": s.tool,
            "input": normalize_for_compare(s.input),
            "result_preview": s.result_preview,
            "planner_phase": s.planner_phase,
        }
        for s in tr.steps
    ]
    judges = [
        {
            "satisfied": j.satisfied,
            "rationale": j.rationale,
            "feedback_for_planner": j.feedback_for_planner,
        }
        for j in tr.judge_rounds
    ]
    return {
        "question": tr.question,
        "error": tr.error,
        "final_text": tr.final_text,
        "graph_focus_node_id": tr.graph_focus_node_id,
        "synthesis_rationale": tr.synthesis_rationale,
        "steps": steps,
        "judge_rounds": judges,
        "raw_messages": tr.raw_messages,
    }


@dataclass(frozen=True)
class NlDualCompareResult:
    left_label: str
    right_label: str
    left_ms: float
    right_ms: float
    left: ToolAgentResult
    right: ToolAgentResult
    normalized_match: bool
    mismatch_detail: str | None
    #: Populated when graphs were loaded in this run (for Streamlit ``keep_cache``).
    cached_graph_pair: tuple[nx.DiGraph, nx.DiGraph] | None = None
    cached_graph_csv: nx.DiGraph | None = None


def run_nl_dual_hydrate(
    question: str,
    *,
    max_rounds: int | None = None,
    cached_graphs: tuple[nx.DiGraph, nx.DiGraph] | None = None,
) -> tuple[NlDualCompareResult, float | None, float | None]:
    """
    Run investigation on CSV graph vs Neo4j-hydrated graph (both use NetworkX tool execution).

    Returns ``(result, hydrate_csv_ms, hydrate_neo_ms)`` — hydrate times ``None`` when graphs were cached.
    """
    if not (question or "").strip():
        raise ValueError("Question is empty.")

    prev = qg._graph
    try:
        hydrate_csv_ms: float | None
        hydrate_neo_ms: float | None
        pair_for_cache: tuple[nx.DiGraph, nx.DiGraph] | None
        if cached_graphs is not None:
            G_csv, G_neo = cached_graphs
            hydrate_csv_ms = None
            hydrate_neo_ms = None
            pair_for_cache = None
        else:
            t0 = time.perf_counter()
            G_csv = qg._load_graph_from_csv_files()
            hydrate_csv_ms = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            G_neo = fetch_di_graph_from_neo4j()
            hydrate_neo_ms = (time.perf_counter() - t0) * 1000
            pair_for_cache = (G_csv, G_neo)

        t0 = time.perf_counter()
        with temporary_graph(G_csv), force_networkx_reads():
            left = run_tool_planner_agent(question.strip(), max_rounds=max_rounds)
        left_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        with temporary_graph(G_neo), force_networkx_reads():
            right = run_tool_planner_agent(question.strip(), max_rounds=max_rounds)
        right_ms = (time.perf_counter() - t0) * 1000

        ln = normalize_for_compare(tool_agent_result_for_compare(left))
        rn = normalize_for_compare(tool_agent_result_for_compare(right))
        ok, msg = diff_summary(ln, rn, "nl_investigation", fromfile="csv_nx", tofile="neo_hydrate_nx")

        return (
            NlDualCompareResult(
                left_label="CSV → NetworkX",
                right_label="Neo4j hydrate → NetworkX",
                left_ms=left_ms,
                right_ms=right_ms,
                left=left,
                right=right,
                normalized_match=ok,
                mismatch_detail=None if ok else msg,
                cached_graph_pair=pair_for_cache,
            ),
            hydrate_csv_ms,
            hydrate_neo_ms,
        )
    finally:
        qg._graph = prev


def run_nl_dual_nx_vs_cypher(
    question: str,
    *,
    max_rounds: int | None = None,
    cached_graph: nx.DiGraph | None = None,
) -> tuple[NlDualCompareResult, float | None]:
    """
    Same CSV graph: NetworkX scan vs native Cypher for ported tools.

    Returns ``(result, hydrate_csv_ms)`` — hydrate ``None`` when *cached_graph* is passed.
    """
    if not (question or "").strip():
        raise ValueError("Question is empty.")

    prev = qg._graph
    try:
        g_for_cache: nx.DiGraph | None
        if cached_graph is not None:
            G_csv = cached_graph
            hydrate_csv_ms = None
            g_for_cache = None
        else:
            t0 = time.perf_counter()
            G_csv = qg._load_graph_from_csv_files()
            hydrate_csv_ms = (time.perf_counter() - t0) * 1000
            g_for_cache = G_csv

        t0 = time.perf_counter()
        with temporary_graph(G_csv), force_networkx_reads():
            left = run_tool_planner_agent(question.strip(), max_rounds=max_rounds)
        left_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        with temporary_graph(G_csv), temporary_neo4j_read_native():
            right = run_tool_planner_agent(question.strip(), max_rounds=max_rounds)
        right_ms = (time.perf_counter() - t0) * 1000

        ln = normalize_for_compare(tool_agent_result_for_compare(left))
        rn = normalize_for_compare(tool_agent_result_for_compare(right))
        ok, msg = diff_summary(ln, rn, "nl_investigation", fromfile="nx_scan", tofile="cypher")

        return (
            NlDualCompareResult(
                left_label="NetworkX scan",
                right_label="Neo4j Cypher (native reads)",
                left_ms=left_ms,
                right_ms=right_ms,
                left=left,
                right=right,
                normalized_match=ok,
                mismatch_detail=None if ok else msg,
                cached_graph_csv=g_for_cache,
            ),
            hydrate_csv_ms,
        )
    finally:
        qg._graph = prev
