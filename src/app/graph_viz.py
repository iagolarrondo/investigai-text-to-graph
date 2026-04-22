"""
Shared interactive graph visualization (pyvis + vis.js) for Streamlit.

Used by the main app (result subgraph) and the Full Interactive Graph page.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Literal

import networkx as nx

# ── Styling (aligned with Interactive Graph page) ─────────────────────────────
TYPE_COLOR: dict[str, str] = {
    "Person": "#7eb6ff",
    "Business": "#5cb85c",
    "Policy": "#f0ad4e",
    "Claim": "#d9534f",
    "Address": "#c879ff",
    "BankAccount": "#aaaaaa",
}
_DEFAULT_COLOR = "#dddddd"

_TYPE_SHAPE: dict[str, str] = {
    "Person": "dot",
    "Business": "square",
    "Policy": "diamond",
    "Claim": "star",
    "Address": "triangleDown",
    "BankAccount": "hexagon",
}
_DEFAULT_SHAPE = "dot"

_EDGE_COLOR: dict[str, str] = {
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
_DEFAULT_EDGE_COLOR = "#888888"


def node_tooltip(node_id: str, data: dict) -> str:
    ntype = data.get("node_type", "")
    label = data.get("label", node_id)
    props: dict = {}
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


def nodes_within_depth(G: nx.DiGraph, start: str, depth: int) -> set[str]:
    """BFS on undirected view up to ``depth`` hops."""
    U = G.to_undirected()
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start, 0)]
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


def build_pyvis_html(
    G: nx.DiGraph,
    *,
    mode: Literal["full", "subgraph"],
    visible_nodes: set[str] | None = None,
    include_types: set[str] | None = None,
    focus_node: str | None = None,
    hop_depth: int = 2,
    physics: bool = True,
    edge_labels: bool = True,
    height_px: int = 680,
    allowed_edge_types: frozenset[str] | None = None,
) -> str:
    """
    Build a self-contained HTML string for ``components.html``.

    * **full** — ``include_types`` required; optional ``focus_node`` + ``hop_depth`` narrows the set.
    * **subgraph** — ``visible_nodes`` required (only these nodes and edges between them are drawn).
    * **allowed_edge_types** — if set (e.g. person–person relationship types), only those edges are drawn.
    """
    try:
        from pyvis.network import Network
    except ImportError as e:
        raise ImportError("pyvis is required. Install with: pip install pyvis") from e

    if mode == "subgraph":
        if visible_nodes is None:
            raise ValueError("subgraph mode requires visible_nodes")
        vn = {n for n in visible_nodes if n in G}
    else:
        if include_types is None:
            raise ValueError("full mode requires include_types")
        if focus_node and focus_node in G:
            neighbourhood = nodes_within_depth(G, focus_node, hop_depth)
            vn = {
                n for n in neighbourhood
                if G.nodes[n].get("node_type", "Unknown") in include_types
            }
        else:
            vn = {
                n for n, d in G.nodes(data=True)
                if d.get("node_type", "Unknown") in include_types
            }

    net = Network(
        height=f"{height_px}px",
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

    active_focus = focus_node if (focus_node and focus_node in vn) else None

    for node_id in vn:
        data = dict(G.nodes[node_id])
        ntype = data.get("node_type", "Unknown")
        label = (data.get("label") or node_id)
        if len(label) > 22:
            label = label[:19] + "…"

        color = TYPE_COLOR.get(ntype, _DEFAULT_COLOR)
        shape = _TYPE_SHAPE.get(ntype, _DEFAULT_SHAPE)
        tooltip = node_tooltip(node_id, data)

        is_root = node_id == active_focus
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

    for u, v, edata in G.edges(data=True):
        if u not in vn or v not in vn:
            continue
        etype = edata.get("edge_type", "")
        if allowed_edge_types is not None and etype not in allowed_edge_types:
            continue
        ecolor = _EDGE_COLOR.get(etype, _DEFAULT_EDGE_COLOR)
        is_direct = active_focus and (u == active_focus or v == active_focus)
        net.add_edge(
            u,
            v,
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

    # When the server passes a focus node (e.g. from the Node inspector), run the same
    # client-side isolate step after load so the iframe status bar matches a graph click.
    initial_focus_js = "null" if not active_focus else json.dumps(active_focus)

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
  var INITIAL_FOCUS = {initial_focus_js};
  var _isolated = false;

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

  (function waitForNetwork() {{
    if (typeof network === 'undefined') {{ setTimeout(waitForNetwork, 100); return; }}
    network.on('click', function(params) {{
      if (params.nodes.length > 0) {{
        isolateNode(params.nodes[0]);
      }} else if (!params.event.srcEvent.defaultPrevented) {{
        if (_isolated) resetGraph();
      }}
    }});
    if (INITIAL_FOCUS) {{
      isolateNode(INITIAL_FOCUS);
    }}
  }})();
</script>
"""
    return html.replace("</body>", custom_js + "\n</body>")
