"""
Interactive Graph Explorer — InvestigAI PoC v1

Full-graph interactive network visualization using pyvis.
Supports filtering by node type, highlighting N-hop neighborhoods,
and click-to-inspect node details.

Run the parent app from project root:
    PYTHONPATH=. streamlit run src/app/app.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import networkx as nx
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.graph_query.query_graph import get_graph, load_graph  # noqa: E402

# ── Node type colours (hex) ────────────────────────────────────────────────────
_TYPE_COLOR: dict[str, str] = {
    "Person": "#7eb6ff",
    "Business": "#5cb85c",
    "Policy": "#f0ad4e",
    "Claim": "#d9534f",
    "Address": "#c879ff",
    "BankAccount": "#aaaaaa",
}
_DEFAULT_COLOR = "#dddddd"

# ── Node type icons (unicode or emoji used as label prefix) ────────────────────
_TYPE_SHAPE: dict[str, str] = {
    "Person": "dot",
    "Business": "square",
    "Policy": "diamond",
    "Claim": "star",
    "Address": "triangleDown",
    "BankAccount": "hexagon",
}
_DEFAULT_SHAPE = "dot"

# ── Edge colours by relationship ───────────────────────────────────────────────
_EDGE_COLOR: dict[str, str] = {
    "IS_CLAIM_AGAINST_POLICY": "#d9534f",
    "IS_COVERED_BY": "#7eb6ff",
    "SOLD_POLICY": "#f0ad4e",
    "LOCATED_IN": "#c879ff",
    "HOLD_BY": "#aaaaaa",
    "IS_SPOUSE_OF": "#ff79c6",
    "IS_RELATED_TO": "#79c6ff",
    "ACT_ON_BEHALF_OF": "#ffb347",
    "HIPAA_AUTHORIZED_ON": "#90ee90",
    "DIAGNOSED_BY": "#ff6961",
}
_DEFAULT_EDGE_COLOR = "#888888"


def _load() -> None:
    """Load graph if not already in memory."""
    try:
        get_graph()
    except RuntimeError:
        load_graph()


def _node_tooltip(node_id: str, data: dict) -> str:
    ntype = data.get("node_type", "")
    label = data.get("label", node_id)
    props = {}
    raw = data.get("properties_json")
    if raw:
        try:
            props = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            props = {}
    lines = [f"<b>{label}</b>", f"<i>{ntype}</i>", f"ID: {node_id}"]
    for k, v in list(props.items())[:10]:
        if v not in (None, "", "nan"):
            lines.append(f"{k}: {v}")
    return "<br>".join(lines)


def _build_pyvis_html(
    G: nx.DiGraph,
    include_types: set[str],
    focus_node: str | None,
    hop_depth: int,
    physics: bool,
    edge_labels: bool,
) -> str:
    try:
        from pyvis.network import Network
    except ImportError:
        st.error("pyvis not installed. Run: `.venv/bin/pip install pyvis`")
        st.stop()

    net = Network(
        height="680px",
        width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="#ffffff",
    )

    if physics:
        net.barnes_hut(
            gravity=-8000,
            central_gravity=0.3,
            spring_length=150,
            spring_strength=0.04,
            damping=0.09,
        )
    else:
        net.toggle_physics(False)

    # Always render all type-filtered nodes — isolation is handled client-side via JS.
    # If a sidebar focus node is set, pre-restrict to its neighbourhood server-side.
    if focus_node and focus_node in G:
        neighbourhood = _nodes_within_depth(G, focus_node, hop_depth)
        visible_nodes = {
            n for n in neighbourhood
            if G.nodes[n].get("node_type", "Unknown") in include_types
        }
    else:
        visible_nodes = {
            n for n, d in G.nodes(data=True)
            if d.get("node_type", "Unknown") in include_types
        }

    for node_id in visible_nodes:
        data = dict(G.nodes[node_id])
        ntype = data.get("node_type", "Unknown")
        label = (data.get("label") or node_id)
        if len(label) > 22:
            label = label[:19] + "…"

        color = _TYPE_COLOR.get(ntype, _DEFAULT_COLOR)
        shape = _TYPE_SHAPE.get(ntype, _DEFAULT_SHAPE)
        tooltip = _node_tooltip(node_id, data)

        is_root = node_id == focus_node
        net.add_node(
            node_id,
            label=("⭐ " + label) if is_root else label,
            title=tooltip,
            color={
                "background": "#ffffff" if is_root else color,
                "border": "#ffffff" if is_root else "#ffffff33",
                "highlight": {"background": "#ffff99", "border": "#ffff00"},
            },
            shape="star" if is_root else shape,
            font={"color": "#000000" if is_root else "#eeeeee", "size": 15 if is_root else 13, "bold": is_root},
            borderWidth=5 if is_root else 1,
            size=36 if is_root else 20,
        )

    for u, v, data in G.edges(data=True):
        if u not in visible_nodes or v not in visible_nodes:
            continue
        etype = data.get("edge_type", "")
        ecolor = _EDGE_COLOR.get(etype, _DEFAULT_EDGE_COLOR)
        is_direct = focus_node and (u == focus_node or v == focus_node)
        net.add_edge(
            u, v,
            title=etype,
            label=etype if edge_labels else "",
            color=ecolor,
            arrows="to",
            width=3 if is_direct else 1.5,
            font={"size": 9, "color": "#cccccc", "strokeWidth": 0},
            smooth={"type": "curvedCW", "roundness": 0.15},
        )

    net.set_options("""
    var options = {
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "navigationButtons": true,
        "keyboard": { "enabled": true }
      },
      "edges": { "arrowStrikethrough": false }
    }
    """)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        html = Path(f.name).read_text()

    # ── Inject client-side click-to-isolate + reset button ────────────────────
    custom_js = f"""
<style>
  #ctrl-bar {{
    position: absolute;
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 999;
    display: flex;
    gap: 8px;
    align-items: center;
    background: rgba(20,20,40,0.85);
    padding: 6px 14px;
    border-radius: 20px;
    border: 1px solid #444;
    font-family: sans-serif;
    font-size: 13px;
    color: #ddd;
    pointer-events: auto;
  }}
  #ctrl-bar button {{
    background: #2a2a4a;
    color: #fff;
    border: 1px solid #666;
    border-radius: 12px;
    padding: 4px 14px;
    cursor: pointer;
    font-size: 12px;
    transition: background 0.15s;
  }}
  #ctrl-bar button:hover {{ background: #4a4a8a; }}
  #ctrl-bar button.active {{ background: #5555aa; border-color: #aaa; }}
  #status-label {{ white-space: nowrap; }}
</style>

<div id="ctrl-bar">
  <span id="status-label">Click a node to isolate</span>
  <button id="reset-btn" onclick="resetGraph()">&#8635; Reset</button>
</div>

<script type="text/javascript">
  var HOP_DEPTH = {hop_depth};
  var _isolated = false;

  // BFS on undirected adjacency — uses vis.js network.getConnectedNodes()
  function getNeighbourhood(nodeId, depth) {{
    var visited = new Set([nodeId]);
    var frontier = [nodeId];
    for (var d = 0; d < depth; d++) {{
      var next = [];
      frontier.forEach(function(n) {{
        network.getConnectedNodes(n).forEach(function(nb) {{
          if (!visited.has(nb)) {{ visited.add(nb); next.push(nb); }}
        }});
      }});
      frontier = next;
    }}
    return visited;
  }}

  function isolateNode(nodeId) {{
    var hood = getNeighbourhood(nodeId, HOP_DEPTH);
    var allNodes = nodes.getIds();
    var allEdges = edges.getIds();

    nodes.update(allNodes.map(function(id) {{
      return {{ id: id, hidden: !hood.has(id) }};
    }}));
    edges.update(allEdges.map(function(id) {{
      var e = edges.get(id);
      return {{ id: id, hidden: !hood.has(e.from) || !hood.has(e.to) }};
    }}));

    _isolated = true;
    document.getElementById('status-label').textContent =
      hood.size + ' node(s) within ' + HOP_DEPTH + ' hop(s) of "' + nodeId + '"';
    document.getElementById('reset-btn').classList.add('active');
  }}

  function resetGraph() {{
    nodes.update(nodes.getIds().map(function(id) {{ return {{ id: id, hidden: false }}; }}));
    edges.update(edges.getIds().map(function(id) {{ return {{ id: id, hidden: false }}; }}));
    _isolated = false;
    document.getElementById('status-label').textContent = 'Click a node to isolate';
    document.getElementById('reset-btn').classList.remove('active');
  }}

  // Wait until vis network is ready, then attach click handler
  (function waitForNetwork() {{
    if (typeof network === 'undefined') {{ setTimeout(waitForNetwork, 100); return; }}
    network.on('click', function(params) {{
      if (params.nodes.length > 0) {{
        isolateNode(params.nodes[0]);
      }} else if (!params.event.srcEvent.defaultPrevented) {{
        // Clicking empty canvas resets
        if (_isolated) resetGraph();
      }}
    }});
  }})();
</script>
"""
    # Inject before </body>
    return html.replace("</body>", custom_js + "\n</body>")


def _nodes_within_depth(G: nx.DiGraph, start: str, depth: int) -> set[str]:
    """BFS on undirected view up to `depth` hops."""
    U = G.to_undirected()
    visited: set[str] = set()
    queue = [(start, 0)]
    while queue:
        node, d = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        if d < depth:
            for nb in U.neighbors(node):
                if nb not in visited:
                    queue.append((nb, d + 1))
    return visited


# ── Page layout ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Interactive Graph — InvestigAI", layout="wide", page_icon="🕸️")
st.title("🕸️ Interactive Graph Explorer")
st.markdown(
    "Explore the full investigation graph. **Hover** nodes for details, "
    "**drag** to rearrange, **scroll** to zoom, **click** to select."
)

try:
    _load()
except (FileNotFoundError, Exception) as e:
    st.error(f"Could not load graph: {e}")
    st.stop()

G = get_graph()

# ── Sidebar controls ───────────────────────────────────────────────────────────
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
    node_ids_sorted = sorted(G.nodes())
    focus_node = st.selectbox(
        "Focus node — isolates its N-hop neighbourhood",
        options=["— none —"] + node_ids_sorted,
        index=0,
    )
    hop_depth = st.slider("Hop depth", min_value=1, max_value=5, value=2,
                           help="How many hops away from the focus node to include.")

    st.markdown("---")
    st.subheader("Display options")
    physics_on = st.toggle("Physics simulation", value=True,
                            help="Turn off for a stable layout after dragging.")
    show_edge_labels = st.toggle("Edge labels", value=True,
                                  help="Shows relationship type on each edge.")

    st.markdown("---")
    # Legend
    st.subheader("Legend")
    for ntype, color in _TYPE_COLOR.items():
        shape = _TYPE_SHAPE.get(ntype, "●")
        st.markdown(
            f'<span style="background:{color};padding:2px 8px;border-radius:4px;'
            f'color:#000;font-size:12px">&nbsp;{ntype}&nbsp;</span>',
            unsafe_allow_html=True,
        )

# ── Resolve focus node ────────────────────────────────────────────────────────
active_focus = focus_node if (focus_node != "— none —" and focus_node in G) else None

if active_focus:
    neighbourhood = _nodes_within_depth(G, active_focus, hop_depth)
    graph_nodes = {n for n in neighbourhood if G.nodes[n].get("node_type", "Unknown") in include_types}
    graph_edges = [(u, v) for u, v in G.edges() if u in graph_nodes and v in graph_nodes]
    st.info(
        f"Showing **{len(graph_nodes)}** nodes within **{hop_depth}** hop(s) of `{active_focus}` "
        f"— all other nodes are hidden."
    )
else:
    graph_nodes = {n for n, d in G.nodes(data=True) if d.get("node_type", "Unknown") in include_types}
    graph_edges = [(u, v) for u, v in G.edges() if u in graph_nodes and v in graph_nodes]

# ── Stats row ─────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Showing nodes", len(graph_nodes))
c2.metric("Showing edges", len(graph_edges))
c3.metric("Total nodes", G.number_of_nodes())
c4.metric("Total edges", G.number_of_edges())

# ── Render graph ──────────────────────────────────────────────────────────────
if not include_types:
    st.warning("Select at least one node type in the sidebar.")
else:
    with st.spinner("Rendering graph…"):
        html = _build_pyvis_html(G, include_types, active_focus, hop_depth, physics_on, show_edge_labels)
    components.html(html, height=700, scrolling=False)

# ── Node inspector ────────────────────────────────────────────────────────────
st.divider()
st.subheader("Node inspector")
inspect_id = st.selectbox(
    "Select a node to inspect its properties and direct connections",
    options=["— pick one —"] + sorted(G.nodes()),
    index=0,
    key="inspector",
)

if inspect_id != "— pick one —" and inspect_id in G:
    data = dict(G.nodes[inspect_id])
    ntype = data.get("node_type", "Unknown")
    label = data.get("label", inspect_id)

    col1, col2 = st.columns([1, 2])
    with col1:
        color = _TYPE_COLOR.get(ntype, _DEFAULT_COLOR)
        st.markdown(
            f'<div style="background:{color};padding:12px;border-radius:8px;color:#000">'
            f'<b style="font-size:18px">{label}</b><br>'
            f'<span style="font-size:13px">{ntype} · <code>{inspect_id}</code></span>'
            f'</div>',
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
            st.dataframe(
                pd.DataFrame({"field": list(props.keys()), "value": list(props.values())}),
                hide_index=True, use_container_width=True,
            )

    with col2:
        out_edges = [(v, G[inspect_id][v].get("edge_type", "")) for v in G.successors(inspect_id)]
        in_edges = [(u, G[u][inspect_id].get("edge_type", "")) for u in G.predecessors(inspect_id)]

        st.markdown(f"**Outgoing edges** ({len(out_edges)})")
        if out_edges:
            st.dataframe(
                pd.DataFrame(out_edges, columns=["target_node", "edge_type"]),
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("None")

        st.markdown(f"**Incoming edges** ({len(in_edges)})")
        if in_edges:
            st.dataframe(
                pd.DataFrame(in_edges, columns=["source_node", "edge_type"]),
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("None")
