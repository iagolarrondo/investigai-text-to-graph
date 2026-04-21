"""
InvestigAI PoC v1 — Streamlit UI.

Loads the graph from ``data/processed/*.csv`` (via ``query_graph``). Investigation
runs through an LLM **tool-planner** → **coverage judge** (full tool trace, uncapped
outer loop) → **synthesis** (user-visible answer + graph focus). Set ``INVESTIGATION_LLM`` to
``gemini`` (``GEMINI_API_KEY``), ``anthropic`` (``ANTHROPIC_API_KEY``), or ``ollama`` (local Ollama; see README).

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
                "The graph centers on one **focus** node (synthesis focus when set, otherwise anchors from the run), "
                "then includes every node within this many **undirected** hops on the full link chart. "
                "Does not re-run the LLM."
            ),
        )
        visible, focus, _mode, edge_filter, slice_hint = compute_summary_visible_nodes(
            G, tr, anchors, hop_depth=hop
        )
        if not visible:
            st.caption(
                "No graph anchors were found (no `Person|…` / `Claim|…` style ids in tool inputs "
                "or in the answer text). Run a question that resolves specific entities, or check the tool steps."
            )
            return
        if slice_hint:
            st.caption(slice_hint)
        st.caption(
            f"**{len(visible)}** nodes · **{len({a for a in anchors if a in G})}** anchor(s) · hop **{hop}** "
            "(focus: synthesis **graph_focus** when present, else tool inputs → results → answer)."
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
    """Tool trace, judge rounds (internal), synthesis answer, and summary graph."""
    st.subheader("Investigation")
    if tr.error:
        st.error(tr.error)
        return
    if not tr.steps and not tr.final_text:
        st.warning("No tool steps and no answer returned.")
        return
    st.caption(
        f"Planner API calls (this run): **{tr.raw_messages}** · "
        "User-facing prose is **only** from synthesis below."
    )
    if getattr(tr, "judge_rounds", None):
        st.subheader("Reviewer (coverage)")
        for j, jr in enumerate(tr.judge_rounds, start=1):
            label = "Satisfied — proceed to synthesis" if jr.satisfied else "Not satisfied — more tools"
            with st.expander(f"Round {j}: {label}", expanded=False):
                st.markdown(jr.rationale)
                if jr.feedback_for_planner:
                    st.text(jr.feedback_for_planner)

    current_phase: int | None = None
    for i, step in enumerate(tr.steps, start=1):
        if current_phase != step.planner_phase:
            current_phase = step.planner_phase
            st.markdown(f"**Planner phase {current_phase}**")
        preview = step.result_preview
        if len(preview) > 12000:
            preview = preview[:12000] + "\n\n…(truncated for display)…"
        with st.expander(f"Step {i}: `{step.tool}`", expanded=(i == 1 and len(tr.steps) <= 3)):
            st.json(step.input)
            st.text(preview)
    st.divider()
    st.subheader("Answer")
    if tr.final_text:
        st.markdown(tr.final_text)
    else:
        st.caption("_(No synthesis answer — inspect tool steps and errors above.)_")
    if getattr(tr, "synthesis_rationale", ""):
        st.caption(f"Graph focus rationale: {tr.synthesis_rationale}")
    if getattr(tr, "graph_focus_node_id", None):
        st.caption(f"Synthesis graph focus: `{tr.graph_focus_node_id}`")
    _render_investigation_graph(tr)


def main() -> None:
    st.set_page_config(
        page_title="InvestigAI PoC v1",
        page_icon="🔎",
        layout="wide",
    )

    st.title("InvestigAI")
    st.caption(
        "LTC investigation copilot — an LLM **plans tools**, a **reviewer** checks coverage on the full trace, "
        "then **synthesis** writes the answer you see."
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
                with st.spinner("Running investigation (LLM + graph tools)…"):
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
