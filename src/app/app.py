"""
InvestigAI PoC v1 — Streamlit UI.

Loads the graph from ``data/processed/*.csv`` (via ``query_graph``). Investigation
runs through a single path: **Claude tool-planner** — it chooses and executes
``query_graph`` tools (search, claim network, relationship catalog, …) in
multiple steps, then answers in natural language. Set ``ANTHROPIC_API_KEY`` in
``.env``.

How to run (from the **project root**, the folder that contains ``src/``)::

    streamlit run src/app/app.py

If Streamlit cannot import ``src``, set PYTHONPATH to the project root::

    PYTHONPATH=. streamlit run src/app/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit.components.v1 as components  # noqa: E402

from src.app.graph_viz import build_pyvis_html  # noqa: E402
from src.app.investigation_graph import (  # noqa: E402
    SUMMARY_VIEW_CAPTIONS,
    compute_summary_visible_nodes,
    gather_investigation_anchors,
)
from src.graph_query.query_graph import get_graph, load_graph, summarize_graph  # noqa: E402
from src.llm.tool_agent import ToolAgentResult, run_tool_planner_agent  # noqa: E402


def _ensure_graph_loaded() -> bool:
    """Load CSV graph if not already in memory."""
    from src.graph_query.query_graph import get_graph

    try:
        get_graph()
    except RuntimeError:
        load_graph()
    return True


def _render_investigation_graph(tr: ToolAgentResult) -> None:
    """Single pyvis summary graph from anchors in tool I/O and the answer (no per-step graphs)."""
    anchors = gather_investigation_anchors(tr)
    G = get_graph()
    with st.expander("Investigation graph", expanded=True):
        hop = st.slider(
            "Neighbourhood hops (summary graph)",
            min_value=1,
            max_value=5,
            value=1,
            key="inv_graph_hop",
            help=(
                "Claim/policy questions use a **tight tool-aligned slice** first (hop may apply to fallbacks). "
                "For **person–person** mode, hops follow only personal-tie edges. "
                "Increase hops to widen neighbourhood views. Does not re-run the LLM."
            ),
        )
        visible, focus, view_mode, edge_filter, slice_hint = compute_summary_visible_nodes(
            G, tr, anchors, hop_depth=hop
        )
        if not visible:
            st.caption(
                "No graph anchors were found (no `Person|…` / `Claim|…` style ids in tool inputs "
                "or in the answer text). Run a question that resolves specific entities, or check the tool steps."
            )
            return
        st.caption(SUMMARY_VIEW_CAPTIONS.get(view_mode, SUMMARY_VIEW_CAPTIONS["neighbourhood"]))
        if slice_hint:
            st.caption(slice_hint)
        st.caption(
            f"**{len(visible)}** nodes · **{len({a for a in anchors if a in G})}** anchor(s) · hop **{hop}** "
            "(anchors prioritize **tool inputs**, then tool results, then the written answer)."
        )
        html = build_pyvis_html(
            G,
            mode="subgraph",
            visible_nodes=visible,
            focus_node=focus,
            hop_depth=hop,
            physics=True,
            edge_labels=True,
            height_px=560,
            allowed_edge_types=edge_filter,
        )
        components.html(html, height=580, scrolling=False)


def _render_tool_planner_result(tr: ToolAgentResult) -> None:
    """Trace of tool calls + final narrative from :func:`run_tool_planner_agent`."""
    st.subheader("Investigation")
    if tr.error:
        st.error(tr.error)
        return
    if not tr.steps and not tr.final_text:
        st.warning("No tool steps and no answer returned.")
        return
    st.caption(f"Model rounds (API calls): **{tr.raw_messages}**")
    for i, step in enumerate(tr.steps, start=1):
        preview = step.result_preview
        if len(preview) > 12000:
            preview = preview[:12000] + "\n\n…(truncated for display)…"
        with st.expander(f"Step {i}: `{step.tool}`", expanded=(i == 1 and len(tr.steps) <= 3)):
            st.json(step.input)
            st.text(preview)
    st.divider()
    st.subheader("Answer")
    if tr.final_text:
        st.info(tr.final_text)
    else:
        st.caption("_(No final narrative — inspect tool steps above.)_")
    _render_investigation_graph(tr)


def main() -> None:
    st.set_page_config(
        page_title="InvestigAI PoC v1",
        page_icon="🔎",
        layout="wide",
    )

    st.title("InvestigAI")
    st.caption(
        "LTC investigation copilot — **Claude** plans graph tool calls from your question "
        "(set `ANTHROPIC_API_KEY` in `.env`)."
    )

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
        "Question",
        placeholder=(
            "e.g. What policies is Person|1004 tied to? | "
            "Who shares a bank account at different addresses? | "
            "What entities are within a few hops of Claim|C001?"
        ),
        height=110,
        key="free_text_question",
        help="The assistant picks tools (search, catalogs, claim/person queries, global scans) to answer.",
    )
    run = st.button("Run investigation", type="primary", key="run_query_btn")

    if run:
        q = (question or "").strip()
        if not q:
            st.warning("Enter a question, then click **Run investigation**.")
        else:
            try:
                with st.spinner("Running investigation (Claude + graph tools)…"):
                    st.session_state["last_tool_run"] = run_tool_planner_agent(q)
            except Exception as exc:
                st.error("Run failed — see details below.")
                st.exception(exc)

    last = st.session_state.get("last_tool_run")
    if last is not None:
        _render_tool_planner_result(last)
    elif not question:
        st.caption("Type a question and click **Run investigation**.")


if __name__ == "__main__":
    main()
