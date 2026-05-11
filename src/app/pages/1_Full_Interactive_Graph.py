"""
Full Interactive Graph — InvestigAI PoC v1

Full-graph interactive network visualization using pyvis (shared ``graph_viz`` module).
Supports filtering by node type, highlighting N-hop neighborhoods,
and click-to-inspect node details.

Run the parent app from project root:
    PYTHONPATH=. streamlit run src/app/app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.app.graph_viz import (  # noqa: E402
    TYPE_COLOR,
    build_pyvis_html,
    build_type_overview_html,
    nodes_within_depth,
)
from src.app.ui_theme import inject_secondary_page_layout_reset, inject_sidebar_chrome_styles  # noqa: E402
from src.graph_query.query_graph import get_graph, load_graph  # noqa: E402

_FOCUS_SENTINEL = "— no focus —"


def _load() -> None:
    try:
        get_graph()
    except RuntimeError:
        load_graph()


st.set_page_config(page_title="Full Interactive Graph — InvestigAI", layout="wide", page_icon="🕸️")
inject_sidebar_chrome_styles()
inject_secondary_page_layout_reset()
st.title("🕸️ Full Interactive Graph")
st.markdown(
    "Explore the full investigation graph. **Hover** nodes for details, "
    "**drag** to rearrange, **scroll** to zoom. **Choose a focus node** below or in the sidebar "
    "(same control in both places), or **click** a node in the graph to isolate its N-hop neighborhood."
)

try:
    _load()
except (FileNotFoundError, Exception) as e:
    st.error(f"Could not load graph: {e}")
    st.stop()

G = get_graph()


def _pick_default_focus(graph) -> str | None:
    """Return the highest-degree node, breaking ties by id for stability."""
    if graph.number_of_nodes() == 0:
        return None
    best = max(graph.nodes(), key=lambda n: (graph.degree(n), n))
    return best


if "ig_focus_node" not in st.session_state:
    st.session_state.ig_focus_node = _pick_default_focus(G)
    st.session_state.ig_focus_auto = True
if st.session_state.ig_focus_node is not None and st.session_state.ig_focus_node not in G:
    st.session_state.ig_focus_node = None

node_ids_sorted = sorted(G.nodes())
opts = [_FOCUS_SENTINEL] + node_ids_sorted

with st.expander("Graph complexity — entire dataset", expanded=False):
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()
    avg_degree = (sum(dict(G.degree()).values()) / total_nodes) if total_nodes else 0.0
    max_possible = total_nodes * (total_nodes - 1) if total_nodes > 1 else 1
    density = (total_edges / max_possible) if max_possible else 0.0
    a, b, c, d = st.columns(4)
    a.metric("Total nodes", f"{total_nodes:,}")
    b.metric("Total edges", f"{total_edges:,}")
    c.metric("Avg degree", f"{avg_degree:.2f}")
    d.metric("Density", f"{density:.2e}")

    type_counts: dict[str, int] = {}
    for _, dat in G.nodes(data=True):
        t = dat.get("node_type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    edge_type_counts: dict[str, int] = {}
    for _, _, dat in G.edges(data=True):
        et = dat.get("edge_type", "Unknown")
        edge_type_counts[et] = edge_type_counts.get(et, 0) + 1

    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Nodes by type**")
        st.dataframe(
            pd.DataFrame(
                sorted(type_counts.items(), key=lambda kv: -kv[1]),
                columns=["node_type", "count"],
            ),
            hide_index=True,
            width="stretch",
        )
    with cc2:
        st.markdown("**Edges by type**")
        st.dataframe(
            pd.DataFrame(
                sorted(edge_type_counts.items(), key=lambda kv: -kv[1]),
                columns=["edge_type", "count"],
            ),
            hide_index=True,
            width="stretch",
        )
    st.caption(
        "Rendering the **entire** graph in pyvis can be slow on large datasets. "
        "The page auto-focuses on the highest-degree node; clear the focus below to render everything."
    )


def _focus_label() -> str:
    fid = st.session_state.ig_focus_node
    if fid is None or fid not in G:
        return _FOCUS_SENTINEL
    return fid


def _commit_focus_from_sb() -> None:
    v = st.session_state.sb_focus
    st.session_state.ig_focus_node = None if v == _FOCUS_SENTINEL else v


def _commit_focus_from_insp() -> None:
    v = st.session_state.insp_focus
    st.session_state.ig_focus_node = None if v == _FOCUS_SENTINEL else v


# Keep both selectboxes aligned to the canonical focus (sidebar + main "inspector").
st.session_state.sb_focus = _focus_label()
st.session_state.insp_focus = _focus_label()

with st.sidebar:
    st.header("Graph controls")

    all_types = sorted({d.get("node_type", "Unknown") for _, d in G.nodes(data=True)})
    include_types = set(
        st.multiselect(
            "Show node types",
            options=all_types,
            default=all_types,
        )
    )

    st.markdown("---")
    st.subheader("Isolate node")
    st.selectbox(
        "Focus node — isolates its N-hop neighbourhood",
        options=opts,
        key="sb_focus",
        on_change=_commit_focus_from_sb,
        help="Synced with **Node inspector** in the main view.",
    )
    hop_depth = st.slider(
        "Hop depth",
        min_value=1,
        max_value=3,
        value=1,
        help="How many hops away from the focus node to include (matches click-to-isolate in the graph).",
    )
    node_cap = st.slider(
        "Max nodes to render",
        min_value=50,
        max_value=600,
        value=200,
        step=50,
        help=(
            "Hard cap on how many nodes pyvis draws. Larger values can freeze the browser on dense hubs. "
            "Use the type-level overview (clear focus) for whole-graph shape."
        ),
    )

    st.markdown("---")
    st.subheader("Display options")
    physics_on = st.toggle(
        "Physics (spread layout)",
        value=True,
        help=(
            "On: runs a force-directed layout that spreads connected nodes apart, then freezes. "
            "Off: loads nodes at their stored positions (faster but usually piled up)."
        ),
    )
    show_edge_labels = st.toggle(
        "Edge labels",
        value=True,
        help="Shows relationship type on each edge.",
    )

    st.markdown("---")
    st.subheader("Legend")
    for ntype, color in TYPE_COLOR.items():
        st.markdown(
            f'<span style="background:{color};padding:2px 8px;border-radius:4px;'
            f'color:#000;font-size:12px">&nbsp;{ntype}&nbsp;</span>',
            unsafe_allow_html=True,
        )

active_focus = st.session_state.ig_focus_node if st.session_state.ig_focus_node in G else None

st.subheader("Node inspector")
st.selectbox(
    "Select a node — same as sidebar **Focus node**; updates the graph to that N-hop subgraph",
    options=opts,
    key="insp_focus",
    on_change=_commit_focus_from_insp,
)
st.caption(
    "Choosing a node here applies the same focus as clicking it in the graph: "
    "the view narrows to nodes within the hop depth, and the focus node is highlighted. "
    f"Default focus is the highest-degree node — choose **{_FOCUS_SENTINEL}** for a type-level overview of the whole graph."
)

if active_focus:
    raw_hood = nodes_within_depth(G, active_focus, hop_depth)
    typed_hood = {n for n in raw_hood if G.nodes[n].get("node_type", "Unknown") in include_types}
    truncated = len(typed_hood) > int(node_cap)
    if truncated:
        if active_focus in typed_hood:
            others = sorted(n for n in typed_hood if n != active_focus)
            graph_nodes = {active_focus, *others[: max(0, int(node_cap) - 1)]}
        else:
            graph_nodes = set(sorted(typed_hood)[: int(node_cap)])
    else:
        graph_nodes = typed_hood
    graph_edges = [(u, v) for u, v in G.edges() if u in graph_nodes and v in graph_nodes]
    if truncated:
        st.warning(
            f"`{active_focus}` has **{len(typed_hood):,}** nodes within {hop_depth} hop(s) — "
            f"rendering only **{len(graph_nodes):,}** (cap). Lower the hop depth or raise the cap."
        )
    else:
        st.info(
            f"Showing **{len(graph_nodes):,}** nodes within **{hop_depth}** hop(s) of `{active_focus}`."
        )
else:
    graph_nodes = set()
    graph_edges = []

c1, c2, c3, c4 = st.columns(4)
c1.metric("Showing nodes", len(graph_nodes) if active_focus else "type overview")
c2.metric("Showing edges", len(graph_edges) if active_focus else "—")
c3.metric("Total nodes", f"{G.number_of_nodes():,}")
c4.metric("Total edges", f"{G.number_of_edges():,}")

html: str | None = None
if not include_types:
    st.warning("Select at least one node type in the sidebar.")
elif active_focus is None:
    st.caption(
        "No focus selected — drawing a **type-level overview**: one supernode per node type "
        "(sized by count) with aggregated edges. Pick a focus node above to drill into a specific neighborhood."
    )
    with st.spinner("Rendering overview…"):
        html = build_type_overview_html(G, height_px=680)
else:
    with st.spinner("Rendering graph…"):
        html = build_pyvis_html(
            G,
            mode="full",
            visible_nodes=None,
            include_types=include_types,
            focus_node=active_focus,
            hop_depth=hop_depth,
            physics=physics_on,
            edge_labels=show_edge_labels,
            height_px=680,
            node_cap=int(node_cap),
        )

if html is not None:
    components.html(html, height=700, scrolling=False)

st.divider()
st.markdown("**Node details** (for the focused node)")

inspect_id = active_focus
if inspect_id is None or inspect_id not in G:
    st.caption("Select a focus node above to see properties and direct connections.")
else:
    data = dict(G.nodes[inspect_id])
    ntype = data.get("node_type", "Unknown")
    label = data.get("label", inspect_id)

    col1, col2 = st.columns([1, 2])
    with col1:
        color = TYPE_COLOR.get(ntype, "#dddddd")
        st.markdown(
            f'<div style="background:{color};padding:12px;border-radius:8px;color:#000">'
            f'<b style="font-size:18px">{label}</b><br>'
            f'<span style="font-size:13px">{ntype} · <code>{inspect_id}</code></span>'
            f"</div>",
            unsafe_allow_html=True,
        )

        props = {}
        raw = data.get("properties_json")
        if raw:
            try:
                props = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                props = {}
        if props:
            st.markdown("**Properties**")
            # Coerce values to str so Arrow can serialize mixed JSON scalars (int vs str, etc.).
            st.dataframe(
                pd.DataFrame(
                    {
                        "field": [str(k) for k in props.keys()],
                        "value": ["" if v is None else str(v) for v in props.values()],
                    }
                ),
                hide_index=True,
                width="stretch",
            )

    with col2:
        out_edges = [(v, G[inspect_id][v].get("edge_type", "")) for v in G.successors(inspect_id)]
        in_edges = [(u, G[u][inspect_id].get("edge_type", "")) for u in G.predecessors(inspect_id)]

        st.markdown(f"**Outgoing edges** ({len(out_edges)})")
        if out_edges:
            st.dataframe(
                pd.DataFrame(out_edges, columns=["target_node", "edge_type"]),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("None")

        st.markdown(f"**Incoming edges** ({len(in_edges)})")
        if in_edges:
            st.dataframe(
                pd.DataFrame(in_edges, columns=["source_node", "edge_type"]),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("None")
