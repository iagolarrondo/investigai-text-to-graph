"""
Whether investigation reads hit **Neo4j with Cypher** vs scanning **NetworkX**.

**Architecture (NL → tools → Neo4j)**

1. The planner still selects the same **named tools** (``summarize_graph``, ``search_nodes``, …).
2. **`NEO4J_READ_MODE=native`** — for tools listed in ``NATIVE_READ_TOOLS``, ``query_graph`` delegates to
   ``neo4j_native_reads`` / ``neo4j_native_heavy`` (hand-written Cypher).
3. **`NEO4J_READ_MODE=llm_cypher`** — same tool names, but ``tool_agent`` asks the **investigation LLM**
   to emit read-only Cypher per call; no changes inside ``query_graph`` dispatch.
4. Tools not listed still call ``_require_graph()`` (CSV or Aura hydrate).
5. Recommended: ``NEO4J_READ_MODE=native`` or ``llm_cypher`` + leave ``GRAPH_BACKEND`` unset so ``load_graph()`` uses **CSV**
   for pyvis and unported tools, while Aura stays the investigation read path for ported tools.
   Keep CSV and Aura in sync (``sync_processed``).

Extend native coverage by adding a function to ``neo4j_native_reads`` and a dispatch branch in
``query_graph``, then add the tool name to ``NATIVE_READ_TOOLS``.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

_force_networkx_reads: ContextVar[bool] = ContextVar("_force_networkx_reads", default=False)


def neo4j_llm_cypher_reads_enabled() -> bool:
    """True when each tool call is implemented by **LLM-generated** read Cypher (see ``cypher_tool_execution``)."""
    if _force_networkx_reads.get():
        return False
    v = (os.getenv("NEO4J_READ_MODE") or "").strip().lower()
    return v in ("llm_cypher", "llm-cypher", "llm-authored", "llm")


def neo4j_native_reads_enabled() -> bool:
    if _force_networkx_reads.get():
        return False
    v = (os.getenv("NEO4J_READ_MODE") or "").strip().lower()
    if v in ("llm_cypher", "llm-cypher", "llm-authored", "llm"):
        return False
    return v in ("native", "cypher", "1", "true", "yes")


@contextmanager
def force_networkx_reads():
    """
    Force ``query_graph`` dispatch down the NetworkX path even when ``NEO4J_READ_MODE=native``.

    Used by dual comparisons (NX scan vs Cypher) and tests.
    """
    tok = _force_networkx_reads.set(True)
    try:
        yield
    finally:
        _force_networkx_reads.reset(tok)


@contextmanager
def temporary_neo4j_read_native():
    """
    Set ``NEO4J_READ_MODE=native`` for the block so ported tools use Cypher; restore env after.

    Pair with ``temporary_graph`` on a CSV-backed graph for “NX scan vs Cypher” NL comparisons.
    """
    key = "NEO4J_READ_MODE"
    had = key in os.environ
    prev = os.environ.get(key, "")
    os.environ[key] = "native"
    try:
        yield
    finally:
        if had:
            os.environ[key] = prev
        else:
            os.environ.pop(key, None)


@contextmanager
def temporary_neo4j_read_llm_cypher():
    """
    Set ``NEO4J_READ_MODE=llm_cypher`` for the block; restore env after.

    Investigation tools run via **LLM-authored Cypher** (``cypher_tool_execution``) instead of
    ``neo4j_native_*`` Python. Pair with ``temporary_graph`` on a CSV-backed graph like the dual NX vs Cypher flow.
    """
    key = "NEO4J_READ_MODE"
    had = key in os.environ
    prev = os.environ.get(key, "")
    os.environ[key] = "llm_cypher"
    try:
        yield
    finally:
        if had:
            os.environ[key] = prev
        else:
            os.environ.pop(key, None)


# Tools implemented in ``neo4j_native_reads`` / ``neo4j_native_heavy`` — extend as more are ported.
# Registry extensions additionally dispatch to ``neo4j_native_extensions`` from ``generated/*.py``.
NATIVE_READ_TOOLS: frozenset[str] = frozenset(
    {
        "summarize_graph",
        "get_graph_relationship_catalog",
        "search_nodes",
        "get_neighbors",
        "get_person_policies",
        "get_claim_network",
        "get_claim_subgraph_summary",
        "get_person_subgraph_summary",
        "get_policy_network",
        "policies_with_related_coparties",
        "find_shared_bank_accounts",
        "find_related_people_clusters",
        "find_business_connection_patterns",
    }
)
