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
    nodes_within_depth,
)
from src.graph_query.query_graph import get_graph, load_graph  # noqa: E402

_FOCUS_SENTINEL = "— no focus —"


def _load() -> None:
    try:
        get_graph()
    except RuntimeError:
        load_graph()


st.set_page_config(page_title="Full Interactive Graph — InvestigAI", layout="wide", page_icon="🕸️")
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

if "ig_focus_node" not in st.session_state:
    st.session_state.ig_focus_node = None
if st.session_state.ig_focus_node is not None and st.session_state.ig_focus_node not in G:
    st.session_state.ig_focus_node = None

node_ids_sorted = sorted(G.nodes())
opts = [_FOCUS_SENTINEL] + node_ids_sorted


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
        max_value=5,
        value=2,
        help="How many hops away from the focus node to include (matches click-to-isolate in the graph).",
    )

    st.markdown("---")
    st.subheader("Display options")
    physics_on = st.toggle(
        "Physics simulation",
        value=True,
        help="Turn off for a stable layout after dragging.",
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
    "the view narrows to nodes within the hop depth, and the focus node is highlighted."
)

if active_focus:
    neighbourhood = nodes_within_depth(G, active_focus, hop_depth)
    graph_nodes = {n for n in neighbourhood if G.nodes[n].get("node_type", "Unknown") in include_types}
    graph_edges = [(u, v) for u, v in G.edges() if u in graph_nodes and v in graph_nodes]
    st.info(
        f"Showing **{len(graph_nodes)}** nodes within **{hop_depth}** hop(s) of `{active_focus}` "
        f"— all other nodes are hidden."
    )
else:
    graph_nodes = {n for n, d in G.nodes(data=True) if d.get("node_type", "Unknown") in include_types}
    graph_edges = [(u, v) for u, v in G.edges() if u in graph_nodes and v in graph_nodes]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Showing nodes", len(graph_nodes))
c2.metric("Showing edges", len(graph_edges))
c3.metric("Total nodes", G.number_of_nodes())
c4.metric("Total edges", G.number_of_edges())

if not include_types:
    st.warning("Select at least one node type in the sidebar.")
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
        )
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
