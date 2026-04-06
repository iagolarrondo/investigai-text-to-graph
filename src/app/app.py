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

import json
import os
import re
import sys
from pathlib import Path

import tempfile

import anthropic
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx
import streamlit.components.v1 as components
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
import src.llm.router as _router_mod  # for last_routing_debug

# Accumulates raw LLM I/O for the current query run (reset each run)
_LLM_DEBUG: list[dict] = []

# Matches graph node ids embedded in table cells.
# Supports both old underscore format (person_5001) and Neo4j pipe format (Person|1001).
_NODE_ID_IN_TEXT = re.compile(
    r"(?:"
    r"\b(?:person|claim|policy|bank|business|address)_[A-Za-z0-9.-]+"
    r"|"
    r"\b(?:Person|Claim|Policy|Business|Address|BankAccount)\|[A-Za-z0-9|.+-]+"
    r")"
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

    Scans columns named ``node_id`` or ending with ``_node_id`` directly (these hold
    raw graph IDs), then also text-scans all cells for Neo4j-format IDs like
    ``Person|1001`` or old underscore IDs like ``person_5001``.
    """
    ids: set[str] = set()

    def scan_df(df: pd.DataFrame) -> None:
        for col in df.columns:
            col_lower = col.lower()
            # Collect entire cell value for columns that store node IDs directly
            if col_lower == "node_id" or col_lower.endswith("_node_id"):
                for val in df[col].dropna():
                    v = str(val).strip()
                    if v and v != "nan":
                        ids.add(v)
            # Also regex-scan every cell for embedded node IDs
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
        if isinstance(nd, pd.DataFrame) and not nd.empty:
            scan_df(nd)
        ed = payload.get("edges")
        if isinstance(ed, pd.DataFrame) and not ed.empty:
            scan_df(ed)
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


def _plan_followups_and_answer(
    question: str, kind: str, payload: object
) -> tuple[str, list[dict]]:
    """
    Ask Claude to (a) answer the question and (b) identify up to 2 follow-up graph
    queries that would deepen the investigation.

    Returns ``(initial_answer, follow_ups)`` where ``follow_ups`` is a list of dicts
    with keys ``intent``, ``claim_node_id`` (str | None), and ``reason``.
    Falls back to ``("", [])`` on any error.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "", []

    results_text = _payload_to_text(kind, payload)
    from src.llm.prompts import QUERY_SCENARIOS

    prompt = f"""You are an insurance fraud investigator's assistant with deep knowledge of the InvestigAI graph system.

<query_scenarios>
{QUERY_SCENARIOS}
</query_scenarios>

The investigator asked: "{question}"

Initial graph query results (intent: {kind}):
{results_text}

Respond with valid JSON only — no markdown, no text outside the JSON:
{{
  "answer": "<direct 1–3 sentence answer using specific names, IDs, and values from the data>",
  "follow_ups": [
    {{
      "intent": "<one of: claim_network | claim_subgraph | shared_bank | people_clusters | business_patterns>",
      "claim_node_id": "<graph node id string (e.g. Claim|C001) or null>",
      "reason": "<one sentence: what this follow-up reveals and why it matters>"
    }}
  ]
}}

Rules:
- "follow_ups" must contain 1–2 entries that are genuinely different from the current intent ({kind}) and would add new investigative value based on the results above.
- If no useful follow-up exists, return an empty array for follow_ups.
- claim_node_id must be an actual node id visible in the results above, or null."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        _LLM_DEBUG.append({
            "call": "plan_followups_and_answer",
            "input": prompt,
            "output": raw,
        })
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        parsed = json.loads(raw)
        answer = parsed.get("answer", "")
        follow_ups = [
            fu for fu in (parsed.get("follow_ups") or [])
            if fu.get("intent") in (
                "claim_network", "claim_subgraph", "shared_bank",
                "people_clusters", "business_patterns"
            )
        ]
        return answer, follow_ups[:2]
    except Exception:
        return "", []


def _synthesize_refined_answer(
    question: str,
    original_kind: str,
    original_payload: object,
    followup_results: list[dict],
) -> str:
    """
    After executing follow-up queries, call Claude with all collected data to produce
    a comprehensive, synthesized investigative summary.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    from src.llm.prompts import QUERY_SCENARIOS

    sections = [f"[Primary query — {original_kind}]\n{_payload_to_text(original_kind, original_payload)}"]
    for i, r in enumerate(followup_results, 1):
        fkind = r.get("kind", "unknown")
        fpayload = r.get("payload")
        sections.append(f"[Follow-up {i} — {fkind}]\n{_payload_to_text(fkind, fpayload)}")

    all_data = "\n\n".join(sections)

    prompt = f"""You are an insurance fraud investigator's assistant with deep knowledge of the InvestigAI graph system.

<query_scenarios>
{QUERY_SCENARIOS}
</query_scenarios>

The investigator asked: "{question}"

All investigation data gathered (original query + {len(followup_results)} follow-up(s)):

{all_data}

Synthesize ALL findings into a comprehensive 2–5 sentence investigative summary.
- Lead with the direct answer to the original question.
- Incorporate key findings from the follow-up queries.
- Highlight any suspicious patterns, overlaps, or anomalies across the combined data.
- Use specific names, IDs, and values. Note any domain caveats."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        _LLM_DEBUG.append({
            "call": "synthesize_refined_answer",
            "input": prompt,
            "output": raw,
        })
        return raw
    except Exception:
        return ""


_RESULT_TYPE_COLOR = {
    "Person": "#7eb6ff",
    "Business": "#5cb85c",
    "Policy": "#f0ad4e",
    "Claim": "#d9534f",
    "Address": "#c879ff",
    "BankAccount": "#aaaaaa",
}
_RESULT_TYPE_SHAPE = {
    "Person": "dot",
    "Business": "square",
    "Policy": "diamond",
    "Claim": "star",
    "Address": "triangleDown",
    "BankAccount": "hexagon",
}
_RESULT_EDGE_COLOR = {
    "IS_CLAIM_AGAINST_POLICY": "#d9534f",
    "IS_COVERED_BY": "#7eb6ff",
    "SOLD_POLICY": "#f0ad4e",
    "LOCATED_IN": "#c879ff",
    "HOLD_BY": "#aaaaaa",
    "HELD_BY": "#aaaaaa",
    "IS_SPOUSE_OF": "#ff79c6",
    "IS_RELATED_TO": "#79c6ff",
    "ACT_ON_BEHALF_OF": "#ffb347",
    "HIPAA_AUTHORIZED_ON": "#90ee90",
    "DIAGNOSED_BY": "#ff6961",
}


def _build_result_pyvis_html(G: nx.DiGraph, node_ids: set[str]) -> str:
    """Build a pyvis interactive graph for the induced subgraph of result nodes."""
    try:
        from pyvis.network import Network
    except ImportError:
        return ""

    valid = {n for n in node_ids if n in G}
    if not valid:
        return ""

    net = Network(
        height="520px",
        width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="#ffffff",
    )
    net.barnes_hut(
        gravity=-6000,
        central_gravity=0.4,
        spring_length=140,
        spring_strength=0.05,
        damping=0.1,
    )

    for node_id in valid:
        data = dict(G.nodes[node_id])
        ntype = data.get("node_type", "Unknown")
        label = (data.get("label") or node_id)
        if len(label) > 22:
            label = label[:19] + "…"
        color = _RESULT_TYPE_COLOR.get(ntype, "#dddddd")
        shape = _RESULT_TYPE_SHAPE.get(ntype, "dot")

        # Build tooltip
        import json as _json
        props = {}
        raw = data.get("properties_json")
        if raw:
            try:
                props = _json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                props = {}
        tip_lines = [f"<b>{label}</b>", f"<i>{ntype}</i>", f"ID: {node_id}"]
        for k, v in list(props.items())[:8]:
            if v not in (None, "", "nan"):
                tip_lines.append(f"{k}: {v}")

        net.add_node(
            node_id,
            label=label,
            title="<br>".join(tip_lines),
            color={"background": color, "border": "#ffffff44",
                   "highlight": {"background": "#ffffff", "border": "#ffff00"}},
            shape=shape,
            font={"color": "#eeeeee", "size": 13},
            borderWidth=1,
            size=20,
        )

    for u, v, edata in G.edges(data=True):
        if u not in valid or v not in valid:
            continue
        etype = edata.get("edge_type", "")
        ecolor = _RESULT_EDGE_COLOR.get(etype, "#888888")
        net.add_edge(
            u, v,
            title=etype,
            label=etype,
            color=ecolor,
            arrows="to",
            width=1.5,
            font={"size": 9, "color": "#cccccc", "strokeWidth": 0},
            smooth={"type": "curvedCW", "roundness": 0.15},
        )

    net.set_options("""
    var options = {
      "interaction": {"hover": true, "tooltipDelay": 80,
                      "navigationButtons": true, "keyboard": {"enabled": true}},
      "edges": {"arrowStrikethrough": false}
    }
    """)

    # Inject click-to-isolate + reset (same pattern as Interactive Graph page)
    custom_js = """
<style>
  #res-ctrl {
    position:absolute; top:8px; left:50%; transform:translateX(-50%);
    z-index:999; display:flex; gap:8px; align-items:center;
    background:rgba(20,20,40,0.85); padding:5px 14px; border-radius:20px;
    border:1px solid #444; font-family:sans-serif; font-size:12px; color:#ddd;
  }
  #res-ctrl button {
    background:#2a2a4a; color:#fff; border:1px solid #666;
    border-radius:12px; padding:3px 12px; cursor:pointer; font-size:11px;
  }
  #res-ctrl button:hover { background:#4a4a8a; }
  #res-ctrl button.active { background:#5555aa; border-color:#aaa; }
</style>
<div id="res-ctrl">
  <span id="res-status">Click a node to isolate</span>
  <button id="res-reset" onclick="resReset()">&#8635; Reset</button>
</div>
<script>
  var _resIsolated = false;
  function resNeighbourhood(id, depth) {
    var visited = new Set([id]), frontier = [id];
    for (var d = 0; d < depth; d++) {
      var next = [];
      frontier.forEach(function(n) {
        network.getConnectedNodes(n).forEach(function(nb) {
          if (!visited.has(nb)) { visited.add(nb); next.push(nb); }
        });
      });
      frontier = next;
    }
    return visited;
  }
  function resIsolate(id) {
    var hood = resNeighbourhood(id, 2);
    nodes.update(nodes.getIds().map(function(i) { return {id:i, hidden:!hood.has(i)}; }));
    edges.update(edges.getIds().map(function(i) {
      var e = edges.get(i); return {id:i, hidden:!hood.has(e.from)||!hood.has(e.to)};
    }));
    _resIsolated = true;
    document.getElementById('res-status').textContent = hood.size + ' node(s) around "' + id + '"';
    document.getElementById('res-reset').classList.add('active');
  }
  function resReset() {
    nodes.update(nodes.getIds().map(function(i) { return {id:i, hidden:false}; }));
    edges.update(edges.getIds().map(function(i) { return {id:i, hidden:false}; }));
    _resIsolated = false;
    document.getElementById('res-status').textContent = 'Click a node to isolate';
    document.getElementById('res-reset').classList.remove('active');
  }
  (function wait() {
    if (typeof network === 'undefined') { setTimeout(wait, 100); return; }
    network.on('click', function(p) {
      if (p.nodes.length > 0) resIsolate(p.nodes[0]);
      else if (_resIsolated) resReset();
    });
  })();
</script>
"""

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        html = Path(f.name).read_text()

    return html.replace("</body>", custom_js + "\n</body>")


def _render_dispatch_result(result: dict, question: str = "") -> None:
    """Full free-text result: errors, intent block, tables."""
    _LLM_DEBUG.clear()
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

        # ── Phase 1: answer + identify follow-up queries ────────────────────────
        with st.spinner("Analysing results and planning follow-up queries…"):
            initial_answer, follow_up_specs = _plan_followups_and_answer(
                question, str(kind), payload
            )

        # ── Phase 2: execute follow-up queries ──────────────────────────────────
        followup_results: list[dict] = []
        if follow_up_specs:
            with st.spinner(f"Running {len(follow_up_specs)} follow-up quer{'y' if len(follow_up_specs)==1 else 'ies'}…"):
                for spec in follow_up_specs:
                    from src.llm.router import RouterDecision as _RD
                    dec = _RD(
                        intent=spec["intent"],
                        claim_node_id=spec.get("claim_node_id"),
                        source="llm",
                        reason=spec.get("reason", ""),
                    )
                    r = dispatch_routed_query(dec)
                    if not r.get("error") and r.get("payload") is not None:
                        r["_spec"] = spec
                        followup_results.append(r)

        # ── Phase 3: synthesize refined answer ──────────────────────────────────
        if followup_results:
            with st.spinner("Synthesizing findings…"):
                final_answer = _synthesize_refined_answer(
                    question, str(kind), payload, followup_results
                )
        else:
            final_answer = initial_answer

        st.subheader("Answer")
        if final_answer:
            st.info(final_answer)
        else:
            st.caption("_(Answer unavailable — check ANTHROPIC_API_KEY)_")

        # ── Show follow-up query results in an expander ─────────────────────────
        if followup_results:
            with st.expander(f"Follow-up queries run ({len(followup_results)})", expanded=False):
                for r in followup_results:
                    spec = r.get("_spec", {})
                    st.markdown(f"**Intent:** `{r['kind']}` — {spec.get('reason', '')}")
                    _render_routed_payload(str(r["kind"]), r.get("payload"))
                    st.divider()

        # ── Combined result graph (original + follow-ups) ───────────────────────
        st.divider()
        st.subheader("Result graph")
        G = get_graph()
        all_node_ids: set[str] = set()
        for raw in _collect_node_ids_from_result(str(kind), payload):
            if raw in G:
                all_node_ids.add(raw)
        for r in followup_results:
            for raw in _collect_node_ids_from_result(str(r["kind"]), r.get("payload")):
                if raw in G:
                    all_node_ids.add(raw)

        if all_node_ids:
            with st.spinner("Rendering graph…"):
                graph_html = _build_result_pyvis_html(G, all_node_ids)
            if graph_html:
                components.html(graph_html, height=540, scrolling=False)
            else:
                st.caption("_(Graph unavailable — pyvis not installed)_")
        else:
            st.caption("_(No matching graph nodes found for this result)_")

        # ── Debug: raw LLM I/O ──────────────────────────────────────────────────
        st.divider()
        routing_debug = dict(_router_mod.last_routing_debug)
        all_debug = []
        if routing_debug:
            all_debug.append({"call": "intent_router", **routing_debug})
        all_debug.extend(_LLM_DEBUG)

        with st.expander(f"Debug: raw LLM inputs & outputs ({len(all_debug)} call(s))", expanded=False):
            for i, entry in enumerate(all_debug, 1):
                call_name = entry.get("call", f"call_{i}")
                st.markdown(f"### Call {i}: `{call_name}`")

                if call_name == "intent_router":
                    st.markdown("**System prompt** (intent router):")
                    st.code(entry.get("system_prompt", ""), language="text")
                    st.markdown("**Messages sent** (few-shot examples + user question):")
                    msgs = entry.get("messages", [])
                    # Show only the last user message to keep it readable; full list below
                    user_msgs = [m for m in msgs if m.get("role") == "user"]
                    if user_msgs:
                        st.markdown(f"*Last user message (of {len(msgs)} total including few-shots):*")
                        st.code(user_msgs[-1].get("content", ""), language="text")
                    st.markdown("**Raw response:**")
                    st.code(entry.get("raw_response", ""), language="json")
                else:
                    st.markdown("**Input prompt:**")
                    st.code(entry.get("input", ""), language="text")
                    st.markdown("**Raw output:**")
                    st.code(entry.get("output", ""), language="text")

                if i < len(all_debug):
                    st.divider()


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
