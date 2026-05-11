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


def _pyvis_vis_options_json(*, physics: bool) -> str:
    """
    Full vis.js options for ``Network.set_options``.

    Pyvis replaces ``self.options`` with the parsed dict from ``set_options`` (it does not merge),
    so we must include ``physics`` here. Otherwise vis defaults to physics enabled and nodes drift.
    """
    interaction = {
        "hover": True,
        "tooltipDelay": 100,
        "navigationButtons": True,
        "keyboard": {"enabled": True},
        "zoomSpeed": 0.8,
        "zoomView": True,
        "dragView": True,
    }
    # Scale node sizes + label fonts with zoom so zooming in actually reveals detail.
    nodes_cfg = {
        "scaling": {
            "min": 12,
            "max": 60,
            "label": {
                "enabled": True,
                "min": 12,
                "max": 36,
                "maxVisible": 50,
                "drawThreshold": 4,
            },
        },
        "font": {"strokeWidth": 4, "strokeColor": "#0e0e1f"},
    }
    edges_cfg = {
        "arrowStrikethrough": False,
        "scaling": {
            "label": {"enabled": True, "min": 10, "max": 22, "drawThreshold": 6},
        },
        "font": {"strokeWidth": 3, "strokeColor": "#0e0e1f"},
    }
    if physics:
        # Loose force layout so neighborhoods spread out rather than piling on top of each other.
        phys: dict = {
            "enabled": True,
            "stabilization": {
                "enabled": True,
                "iterations": 320,
                "updateInterval": 20,
                "onlyDynamicEdges": False,
                "fit": True,
            },
            "barnesHut": {
                "gravitationalConstant": -22000,
                "centralGravity": 0.08,
                "springLength": 260,
                "springConstant": 0.025,
                "damping": 0.5,
                "avoidOverlap": 0.7,
            },
            "minVelocity": 0.5,
        }
    else:
        phys = {"enabled": False}
    return json.dumps(
        {
            "interaction": interaction,
            "nodes": nodes_cfg,
            "edges": edges_cfg,
            "physics": phys,
        },
        separators=(",", ":"),
    )


def nodes_within_depth(
    G: nx.DiGraph,
    start: str,
    depth: int,
    *,
    node_cap: int | None = None,
) -> set[str]:
    """BFS on undirected view up to ``depth`` hops.

    If ``node_cap`` is set, stop once ``len(visited) >= node_cap`` so the caller can
    keep render size bounded on dense hubs.
    """
    U = G.to_undirected()
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start, 0)]
    while queue:
        node, d = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        if node_cap is not None and len(visited) >= node_cap:
            break
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
    freeze_physics_after_stabilize: bool = True,
    node_cap: int | None = None,
) -> str:
    """
    Build a self-contained HTML string for ``components.html``.

    * **full** — ``include_types`` required; optional ``focus_node`` + ``hop_depth`` narrows the set.
    * **subgraph** — ``visible_nodes`` required (only these nodes and edges between them are drawn).
    * **allowed_edge_types** — if set (e.g. person–person relationship types), only those edges are drawn.
    * **freeze_physics_after_stabilize** — when ``physics`` is on, disable physics after the first layout
      stabilizes so nodes stop drifting (vis.js ``stabilizationIterationsDone``).
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
            neighbourhood = nodes_within_depth(
                G, focus_node, hop_depth, node_cap=node_cap
            )
            vn = {
                n for n in neighbourhood
                if G.nodes[n].get("node_type", "Unknown") in include_types
            }
        else:
            vn = {
                n for n, d in G.nodes(data=True)
                if d.get("node_type", "Unknown") in include_types
            }
    if node_cap is not None and len(vn) > node_cap:
        # Deterministic trim (sorted) when no focus is set, so the result is stable.
        if focus_node and focus_node in vn:
            others = sorted(n for n in vn if n != focus_node)
            vn = {focus_node, *others[: max(0, node_cap - 1)]}
        else:
            vn = set(sorted(vn)[:node_cap])

    net = Network(
        height=f"{height_px}px",
        width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="#ffffff",
    )

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
                "border": "#ffffff" if is_root else "#ffffff66",
                "highlight": {"background": "#ffff99", "border": "#ffff00"},
            },
            shape="star" if is_root else shape,
            font={
                "color": "#000000" if is_root else "#f4f4f6",
                "size": 20 if is_root else 16,
                "bold": is_root,
                "strokeWidth": 4,
                "strokeColor": "#0e0e1f",
            },
            borderWidth=5 if is_root else 2,
            size=42 if is_root else 24,
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
            width=3.5 if is_direct else 1.8,
            font={
                "size": 12,
                "color": "#d8d8e0",
                "strokeWidth": 3,
                "strokeColor": "#0e0e1f",
                "align": "middle",
            },
            smooth={"type": "curvedCW", "roundness": 0.15},
        )

    net.set_options("var options = " + _pyvis_vis_options_json(physics=physics))

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        html = Path(f.name).read_text()

    # When the server passes a focus node (e.g. from the Node inspector), run the same
    # client-side isolate step after load so the iframe status bar matches a graph click.
    initial_focus_js = "null" if not active_focus else json.dumps(active_focus)
    stabilize_then_stop = bool(physics and freeze_physics_after_stabilize)

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
  var STABILIZE_THEN_STOP_PHYSICS = {json.dumps(stabilize_then_stop)};
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
    if (STABILIZE_THEN_STOP_PHYSICS) {{
      function stopPhysics() {{
        try {{ network.setOptions({{ physics: false }}); }} catch (e) {{}}
      }}
      network.once('stabilizationIterationsDone', stopPhysics);
      network.once('stabilized', stopPhysics);
      setTimeout(stopPhysics, 3500);
    }}
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


def build_type_overview_html(
    G: nx.DiGraph,
    *,
    height_px: int = 680,
) -> str:
    """Aggregated overview: one supernode per node_type, edges grouped by edge_type.

    For very large graphs where drawing every entity is infeasible, this collapses the
    graph to its type-level shape (Person→Policy→Claim, etc.) with counts.
    """
    try:
        from pyvis.network import Network
    except ImportError as e:
        raise ImportError("pyvis is required. Install with: pip install pyvis") from e

    type_counts: dict[str, int] = {}
    for _, d in G.nodes(data=True):
        t = d.get("node_type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    # edge_type counts per (from_type, to_type)
    pair_counts: dict[tuple[str, str], dict[str, int]] = {}
    for u, v, ed in G.edges(data=True):
        ft = G.nodes[u].get("node_type", "Unknown")
        tt = G.nodes[v].get("node_type", "Unknown")
        et = ed.get("edge_type", "Unknown")
        pair_counts.setdefault((ft, tt), {})
        pair_counts[(ft, tt)][et] = pair_counts[(ft, tt)].get(et, 0) + 1

    net = Network(
        height=f"{height_px}px",
        width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="#ffffff",
    )

    # Size supernodes by sqrt(count) so a 10k node type isn't 100× bigger than a 100 one.
    max_count = max(type_counts.values()) if type_counts else 1
    for t, count in sorted(type_counts.items()):
        size = 30 + int(60 * (count / max_count) ** 0.5)
        color = TYPE_COLOR.get(t, _DEFAULT_COLOR)
        shape = _TYPE_SHAPE.get(t, _DEFAULT_SHAPE)
        net.add_node(
            t,
            label=f"{t}\n({count:,})",
            title=f"<b>{t}</b><br>{count:,} nodes",
            color={"background": color, "border": "#ffffff66"},
            shape=shape,
            size=size,
            font={"color": "#ffffff", "size": 16, "bold": True},
            borderWidth=2,
        )

    for (ft, tt), ets in pair_counts.items():
        if ft not in type_counts or tt not in type_counts:
            continue
        total = sum(ets.values())
        top = sorted(ets.items(), key=lambda kv: -kv[1])[:3]
        label = ", ".join(f"{et} ({c:,})" for et, c in top)
        # Use the dominant edge_type's color.
        dominant_et = top[0][0] if top else ""
        ecolor = _EDGE_COLOR.get(dominant_et, _DEFAULT_EDGE_COLOR)
        tooltip = (
            f"<b>{ft} → {tt}</b><br>"
            f"Total edges: {total:,}<br>"
            + "<br>".join(f"{et}: {c:,}" for et, c in sorted(ets.items(), key=lambda kv: -kv[1]))
        )
        net.add_edge(
            ft,
            tt,
            title=tooltip,
            label=label,
            color=ecolor,
            arrows="to",
            width=2 + min(8, total // 2000),
            font={"size": 11, "color": "#cccccc", "strokeWidth": 0},
            smooth={"type": "curvedCW", "roundness": 0.2},
        )

    net.set_options("var options = " + _pyvis_vis_options_json(physics=True))

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        net.save_graph(f.name)
        html = Path(f.name).read_text()

    extra_js = """
<style>
  #ov-banner {
    position: absolute;
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 999;
    background: rgba(20,20,40,0.85);
    border: 1px solid #444;
    color: #ddd;
    padding: 6px 14px;
    border-radius: 20px;
    font-family: sans-serif;
    font-size: 13px;
  }
</style>
<div id="ov-banner">Type-level overview — pick a focus node below to drill into a specific neighborhood</div>
<script type="text/javascript">
  (function waitForNetwork() {
    if (typeof network === 'undefined') { setTimeout(waitForNetwork, 100); return; }
    function stopPhysics() { try { network.setOptions({ physics: false }); } catch (e) {} }
    network.once('stabilizationIterationsDone', stopPhysics);
    network.once('stabilized', stopPhysics);
    setTimeout(stopPhysics, 3500);
  })();
</script>
"""
    return html.replace("</body>", extra_js + "\n</body>")
