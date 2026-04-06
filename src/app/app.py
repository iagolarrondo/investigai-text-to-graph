"""
InvestigAI PoC v1 — minimal Streamlit UI.

Loads the graph from ``data/processed/*.csv`` (via ``query_graph``). You can run
**predefined demos** or **free-text** questions routed by ``src.llm.router``
(rule-based; no LLM API).

After each investigation result, the app shows a **small subgraph**: tables of the
involved nodes and edges, plus a simple diagram.

How to run (from the **project root**, the folder that contains ``src/``)::

    streamlit run src/app/app.py

If Streamlit cannot import ``src``, set PYTHONPATH to the project root::

    PYTHONPATH=. streamlit run src/app/app.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import anthropic
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

# --- Make ``src.*`` importable when running ``streamlit run src/app/app.py`` ---
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.graph_query.query_graph import (  # noqa: E402
    get_graph,
    load_graph,
    summarize_graph,
)
from src.llm.router import (  # noqa: E402
    RouterDecision,
    dispatch_routed_query,
    route_question_rules,
)

# Matches graph node ids embedded in table cells (person_5001, claim_C9000..., policy_POL-...)
_NODE_ID_IN_TEXT = re.compile(
    r"\b(?:person|claim|policy|bank|business|address)_[A-Za-z0-9.-]+\b"
)


# Colors for matplotlib (match notebook spirit)
_TYPE_COLOR = {
    "Person": "#7eb6ff",
    "Business": "#90ee90",
    "Policy": "#ffd580",
    "Claim": "#ff9999",
    "Address": "#d4a5ff",
    "BankAccount": "#c4c4c4",
}

# Keys on investigation payloads that are not DataFrames (skip for subgraph scraping)
_INVESTIGATION_META_KEYS = frozenset(
    {"summary", "explanation_plain", "evidence_bullets", "claim_node_id", "max_depth"}
)

_CLAIM_TABLE_KEYS = (
    "claim",
    "linked_policies",
    "other_claims_on_policy",
    "people_linked_to_policy",
    "claimant_person_match",
)


def _ensure_graph_loaded() -> bool:
    """Load CSV graph if not already in memory."""
    try:
        get_graph()
    except RuntimeError:
        load_graph()
    return True


def _collect_node_ids_from_result(kind: str, payload: object) -> set[str]:
    """
    Pull graph node ids mentioned in query result tables.

    We scan every cell in the result DataFrames for tokens like ``person_5001`` or
    ``policy_POL-LTC-10001`` so comma-separated columns are handled without
    hard-coding every column name.
    """
    ids: set[str] = set()

    def scan_df(df: pd.DataFrame) -> None:
        for col in df.columns:
            for val in df[col].dropna():
                ids.update(_NODE_ID_IN_TEXT.findall(str(val)))

    if kind == "claim_network" and isinstance(payload, dict):
        for k, v in payload.items():
            if k in _INVESTIGATION_META_KEYS:
                continue
            if isinstance(v, pd.DataFrame) and not v.empty:
                scan_df(v)
    elif kind == "claim_subgraph" and isinstance(payload, dict):
        nd = payload.get("nodes")
        if isinstance(nd, pd.DataFrame) and not nd.empty and "node_id" in nd.columns:
            ids.update(nd["node_id"].astype(str).tolist())
    elif isinstance(payload, dict) and "table" in payload:
        t = payload.get("table")
        if isinstance(t, pd.DataFrame) and not t.empty:
            scan_df(t)
    elif isinstance(payload, pd.DataFrame) and not payload.empty:
        scan_df(payload)

    return ids


def _induced_subgraph_tables(G: nx.DiGraph, node_ids: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build node list and edge list for nodes in ``node_ids`` (only edges with both ends inside)."""
    valid = {n for n in node_ids if n in G}
    nrows = []
    for n in sorted(valid):
        d = G.nodes[n]
        nrows.append(
            {
                "node_id": n,
                "node_type": d.get("node_type", ""),
                "label": d.get("label", ""),
            }
        )
    nodes_df = pd.DataFrame(nrows)

    erows = []
    for u, v, data in G.edges(data=True):
        if u in valid and v in valid:
            erows.append(
                {
                    "from_node": u,
                    "to_node": v,
                    "edge_type": data.get("edge_type", ""),
                    "edge_id": data.get("edge_id", ""),
                }
            )
    edges_df = pd.DataFrame(erows)
    return nodes_df, edges_df


def _plot_node_label(node_id: str, data: dict) -> str:
    """
    Two-line label: **node type** (grouping) on line 1, human **name or id** on line 2.
    """
    ntype = str(data.get("node_type") or "Unknown")
    raw = (data.get("label") or "").strip()
    if not raw:
        raw = node_id
    if len(raw) > 26:
        raw = raw[:23] + "…"
    return f"{ntype}\n{raw}"


def _subgraph_diagram_caption(G: nx.DiGraph, node_ids: set[str]) -> str:
    """One short paragraph placed directly above the matplotlib figure."""
    valid = {n for n in node_ids if n in G}
    if not valid:
        return ""
    sub = G.subgraph(valid)
    counts: dict[str, int] = {}
    for n in valid:
        t = str(G.nodes[n].get("node_type") or "Unknown")
        counts[t] = counts.get(t, 0) + 1
    n_edges = sub.number_of_edges()
    parts = [f"**{t}** ({counts[t]})" for t in sorted(counts.keys(), key=lambda k: (-counts[k], k))]
    return (
        f"This **link chart** shows only entities that appeared in the result tables above "
        f"— **{len(valid)}** nodes, **{n_edges}** directed links. "
        f"Types here: {' · '.join(parts)}. "
        "Each bubble is labeled with **type** (top line) and **display name** (bottom). "
        "Arrows follow how the data was stored."
    )


def _subgraph_figure(G: nx.DiGraph, node_ids: set[str]):
    """Draw induced subgraph; return matplotlib Figure or None if empty."""
    valid = {n for n in node_ids if n in G}
    if not valid:
        return None

    sub = G.subgraph(valid).copy()
    fig, ax = plt.subplots(figsize=(11, 7.2), facecolor="#fafafa")
    ax.set_facecolor("#fafafa")

    # Spread nodes a bit more on small graphs so labels do not overlap as much
    k = max(2.0, 5.0 / max(len(sub), 1))
    pos = nx.spring_layout(sub, seed=42, k=k, iterations=120)

    node_list = list(sub.nodes())
    colors = [_TYPE_COLOR.get(sub.nodes[n].get("node_type"), "#dddddd") for n in node_list]
    nx.draw_networkx_nodes(
        sub,
        pos,
        nodelist=node_list,
        node_color=colors,
        node_size=2000,
        alpha=0.95,
        edgecolors="#333333",
        linewidths=0.6,
        ax=ax,
    )

    labels = {n: _plot_node_label(n, sub.nodes[n]) for n in sub.nodes()}
    nx.draw_networkx_labels(
        sub,
        pos,
        labels=labels,
        font_size=8,
        font_family="sans-serif",
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="white",
            edgecolor="#bbbbbb",
            linewidth=0.7,
            alpha=0.94,
        ),
        ax=ax,
    )

    nx.draw_networkx_edges(
        sub,
        pos,
        arrows=True,
        arrowsize=18,
        arrowstyle="-|>",
        edge_color="#4a4a4a",
        width=1.15,
        alpha=0.75,
        connectionstyle="arc3,rad=0.15",
        min_source_margin=18,
        min_target_margin=18,
        ax=ax,
    )

    # Edge relationship names — only when the slice is small enough to stay readable
    if sub.number_of_edges() <= 10:
        edge_lbl = {
            (u, v): str(d.get("edge_type") or "")[:18] for u, v, d in sub.edges(data=True)
        }
        nx.draw_networkx_edge_labels(
            sub,
            pos,
            edge_labels=edge_lbl,
            font_size=6,
            font_color="#333333",
            rotate=False,
            label_pos=0.45,
            bbox=dict(boxstyle="round,pad=0.15", facecolor="#ffffff", edgecolor="none", alpha=0.78),
            ax=ax,
        )

    used_types = sorted({str(sub.nodes[n].get("node_type") or "Unknown") for n in sub.nodes()})
    handles = [
        mpatches.Patch(facecolor=_TYPE_COLOR.get(t, "#dddddd"), edgecolor="#333333", linewidth=0.5, label=t)
        for t in used_types
    ]
    ax.legend(
        handles=handles,
        title="Node type",
        loc="upper left",
        fontsize=8,
        title_fontsize=9,
        framealpha=0.95,
        edgecolor="#cccccc",
    )

    ax.set_title("Link chart for this query (subgraph only)", fontsize=11, pad=12)
    ax.axis("off")

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    if xs and ys:
        pad = 0.22
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)

    fig.tight_layout()
    return fig


def _should_show_subgraph(kind: str, payload: object) -> bool:
    if kind not in (
        "claim_network",
        "claim_subgraph",
        "shared_bank",
        "people_clusters",
        "business_patterns",
    ):
        return False
    if kind == "claim_subgraph" and isinstance(payload, dict):
        nd = payload.get("nodes")
        return isinstance(nd, pd.DataFrame) and not nd.empty
    if isinstance(payload, dict) and "table" in payload:
        t = payload.get("table")
        return isinstance(t, pd.DataFrame) and not t.empty
    if isinstance(payload, pd.DataFrame):
        return not payload.empty
    if kind == "claim_network" and isinstance(payload, dict):
        return any(
            isinstance(v, pd.DataFrame) and not v.empty
            for k, v in payload.items()
            if k not in _INVESTIGATION_META_KEYS
        )
    return payload is not None


def _display_subgraph_section(kind: str, payload: object) -> None:
    """Tables + diagram for nodes/edges touched by this investigation result."""
    if not _should_show_subgraph(kind, payload):
        return

    st.divider()
    st.subheader("Subgraph for this result")
    st.markdown(
        """
We **zoom in** on ids that appeared in the result tables: the **nodes** and **edges**
tables list them explicitly; the **diagram** is the same slice as a small link chart
(layout is automatic, not geography).
        """
    )

    G = get_graph()
    raw_ids = _collect_node_ids_from_result(kind, payload)
    node_ids = {n for n in raw_ids if n in G}

    if not node_ids:
        st.warning(
            "No graph nodes could be inferred from this result (ids in tables did not match "
            "loaded nodes). Try another question or rebuild the graph CSVs."
        )
        return

    nodes_df, edges_df = _induced_subgraph_tables(G, node_ids)

    st.markdown(f"**{len(nodes_df)}** nodes and **{len(edges_df)}** edges in this subgraph.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Nodes in this slice")
        st.dataframe(nodes_df, use_container_width=True, hide_index=True)
    with c2:
        st.markdown("##### Links between them")
        st.dataframe(edges_df, use_container_width=True, hide_index=True)

    fig = _subgraph_figure(G, node_ids)
    if fig is not None:
        st.markdown("##### Diagram")
        st.markdown(_subgraph_diagram_caption(G, node_ids))
        st.pyplot(fig, clear_figure=True)
        plt.close(fig)


def _render_investigation_brief(envelope: dict) -> None:
    """
    Plain-English *why* we returned this result + bullets of graph ids / edge types.

    ``envelope`` is any investigation dict that may include ``explanation_plain`` and
    ``evidence_bullets`` (from ``query_graph``).
    """
    exp = envelope.get("explanation_plain")
    if exp:
        st.markdown("##### Why you are seeing this")
        st.info(exp)
    bullets = envelope.get("evidence_bullets") or []
    if bullets:
        st.markdown("##### Supporting graph links (ids)")
        st.caption(
            "Each line is a **relationship stored in the prototype graph** "
            "(node id → relationship type → node id). Use it to trace the finding in "
            "your link chart or warehouse exports."
        )
        for b in bullets:
            st.markdown(f"- `{b}`")


def _render_claim_network_tables(payload: dict) -> None:
    """Display the dict returned by ``get_claim_network``."""
    _render_investigation_brief(payload)
    summ = payload.get("summary")
    if summ:
        st.markdown("##### Technical summary")
        st.success(summ)

    st.markdown("##### Result tables")
    for key in _CLAIM_TABLE_KEYS:
        df = payload.get(key)
        st.markdown(f"**{key.replace('_', ' ').title()}**")
        if isinstance(df, pd.DataFrame) and not df.empty:
            st.dataframe(df, use_container_width=True)
        elif isinstance(df, pd.DataFrame):
            st.caption("_(empty)_")
        else:
            st.write(df)


def _render_claim_subgraph_tables(payload: dict) -> None:
    """Display the dict returned by ``get_claim_subgraph_summary``."""
    _render_investigation_brief(payload)
    summ = payload.get("summary")
    if summ:
        st.markdown("##### Technical summary")
        st.success(summ)
    depth = payload.get("max_depth")
    cid = payload.get("claim_node_id")
    if cid is not None and depth is not None:
        st.caption(f"Neighborhood radius: **{depth}** undirected hop(s) from `{cid}`.")

    st.markdown("##### Counts by entity type")
    tc = payload.get("type_counts")
    if isinstance(tc, pd.DataFrame) and not tc.empty:
        st.dataframe(tc, use_container_width=True, hide_index=True)
    else:
        st.caption("_(no types)_")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Nodes in neighborhood")
        nodes = payload.get("nodes")
        if isinstance(nodes, pd.DataFrame) and not nodes.empty:
            st.dataframe(nodes, use_container_width=True, hide_index=True)
        else:
            st.caption("_(empty)_")
    with c2:
        st.markdown("##### Edges (both ends inside neighborhood)")
        edges = payload.get("edges")
        if isinstance(edges, pd.DataFrame) and not edges.empty:
            st.dataframe(edges, use_container_width=True, hide_index=True)
        else:
            st.caption("_(empty)_")


def _render_tabular_investigation(envelope: dict, *, empty_warning: str) -> None:
    """Shared bank / people clusters / business patterns envelope from ``query_graph``."""
    _render_investigation_brief(envelope)
    df = envelope.get("table")
    st.markdown("##### Result table")
    if isinstance(df, pd.DataFrame) and df.empty:
        st.warning(empty_warning)
    elif isinstance(df, pd.DataFrame):
        st.dataframe(df, use_container_width=True)
    else:
        st.caption("_(no table)_")


def _render_routed_payload(kind: str, payload: object) -> None:
    """Render ``dispatch_routed_query`` payload by result kind."""
    if kind == "claim_network" and isinstance(payload, dict):
        _render_claim_network_tables(payload)
    elif kind == "claim_subgraph" and isinstance(payload, dict):
        _render_claim_subgraph_tables(payload)
    elif kind == "shared_bank" and isinstance(payload, dict):
        _render_tabular_investigation(
            payload,
            empty_warning="No bank account has two or more holders in this graph.",
        )
    elif kind == "people_clusters" and isinstance(payload, dict):
        _render_tabular_investigation(
            payload,
            empty_warning="No person–person relationship clusters found.",
        )
    elif kind == "business_patterns" and isinstance(payload, dict):
        _render_tabular_investigation(
            payload,
            empty_warning="No business/person colocation rows for this graph.",
        )
    else:
        st.write(payload)

    _display_subgraph_section(kind, payload)


def _show_router_decision(decision: RouterDecision) -> None:
    """Intent panel for free-text flow."""
    st.subheader("Detected intent")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Intent:** `{decision.intent}`")
    c2.markdown(f"**Router:** `{decision.source}` (rule-based keywords)")
    if decision.claim_node_id:
        st.markdown(f"**Claim node id:** `{decision.claim_node_id}`")
    st.caption(decision.reason)
    if decision.matched_keywords:
        st.caption("Matched keywords: " + ", ".join(decision.matched_keywords))



def _payload_to_text(kind: str, payload: object) -> str:
    """Serialise query results to a compact text block for the LLM."""
    lines: list[str] = []

    def _df_summary(label: str, df: pd.DataFrame) -> None:
        if not isinstance(df, pd.DataFrame) or df.empty:
            lines.append(f"{label}: (empty)")
            return
        lines.append(f"{label} ({len(df)} row(s)):")
        lines.append(df.to_string(index=False, max_rows=30))

    if kind == "claim_network" and isinstance(payload, dict):
        for key in ("claim", "linked_policies", "other_claims_on_policy",
                    "people_linked_to_policy", "claimant_person_match"):
            _df_summary(key.replace("_", " ").title(), payload.get(key))
    elif kind == "claim_subgraph" and isinstance(payload, dict):
        tc = payload.get("type_counts")
        if isinstance(tc, pd.DataFrame):
            lines.append("Type counts:\n" + tc.to_string(index=False))
        _df_summary("Nodes", payload.get("nodes"))
        _df_summary("Edges", payload.get("edges"))
    elif isinstance(payload, dict) and "table" in payload:
        _df_summary("Results", payload.get("table"))
    elif isinstance(payload, pd.DataFrame):
        _df_summary("Results", payload)

    return "\n".join(lines) if lines else "(no data)"


def _generate_nl_summary(question: str, kind: str, payload: object) -> str:
    """Call Claude to produce a direct, concise answer to the investigator's question."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    results_text = _payload_to_text(kind, payload)

    prompt = f"""You are an insurance fraud investigator's assistant.

The investigator asked: "{question}"

Graph query results:
{results_text}

Answer the question directly and concisely in 1–3 sentences using only what the results show.
Use specific names, IDs, and values from the data. If the results show nothing suspicious, say so plainly."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return ""


def _render_dispatch_result(result: dict, question: str = "") -> None:
    """Full free-text result: errors, intent block, tables."""
    decision: RouterDecision | None = result.get("decision")
    kind = result.get("kind")
    if result.get("error") and kind in (None, "error", "unknown"):
        st.error(result.get("error", "Unknown error"))
        if decision:
            _show_router_decision(decision)
        return

    if decision:
        _show_router_decision(decision)

    st.markdown("---")
    st.subheader("Result")
    if result.get("error"):
        st.warning(result["error"])

    payload = result.get("payload")
    if kind == "unknown":
        st.info(
            "Try words like **claim**, **neighborhood** / **n-hop**, **bank**, **family**, "
            "or **business**."
        )
        return

    _render_routed_payload(str(kind), payload)

    if question and payload is not None:
        st.divider()
        st.subheader("Answer")
        with st.spinner("Answering…"):
            summary = _generate_nl_summary(question, str(kind), payload)
        if summary:
            st.info(summary)
        else:
            st.caption("_(Answer unavailable — check ANTHROPIC_API_KEY)_")


def main() -> None:
    st.set_page_config(
        page_title="InvestigAI PoC v1",
        page_icon="🔎",
        layout="wide",
    )

    st.title("InvestigAI")

    try:
        _ensure_graph_loaded()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    summary = summarize_graph()
    c1, c2, c3 = st.columns(3)
    c1.metric("Nodes", summary["num_nodes"])
    c2.metric("Edges", summary["num_edges"])
    c3.metric("Directed", "yes" if summary["is_directed"] else "no")

    st.divider()

    question = st.text_area(
        "Ask an investigation question",
        placeholder=(
            "e.g. Did the writing agent also file a claim? | "
            "Who shares a bank account at different addresses? | "
            "Show family and spouse clusters | "
            "Is any ICP checking in far from the policyholder address?"
        ),
        height=90,
        key="free_text_question",
    )
    run = st.button("Run query", type="primary")

    if run:
        q = (question or "").strip()
        if not q:
            st.warning("Enter a question, then click **Run query**.")
        else:
            decision = route_question_rules(q)
            result = dispatch_routed_query(decision)
            _render_dispatch_result(result, question=q)
    elif not question:
        st.caption("Type a question above and click **Run query**.")


if __name__ == "__main__":
    main()
