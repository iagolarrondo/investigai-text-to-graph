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
import time
from pathlib import Path

import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.project_env import load_project_dotenv

    load_project_dotenv()
except ImportError:
    pass

import streamlit.components.v1 as components  # noqa: E402

from src.app.graph_viz import build_pyvis_html  # noqa: E402
from src.app.investigation_graph import (  # noqa: E402
    compute_summary_visible_nodes,
    gather_investigation_anchors,
)
from src.app.entity_resolution import (  # noqa: E402
    candidate_nodes,
    fallback_mentions,
    format_candidate_option,
    locate_mention_span,
    question_already_has_node_ids,
    rewrite_question,
)
from src.graph_query.native_read_mode import (
    force_networkx_reads,
    temporary_neo4j_read_llm_cypher,
    temporary_neo4j_read_native,
)  # noqa: E402
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


def _render_investigation_graph(tr: ToolAgentResult, *, key_suffix: str = "") -> None:
    """Single pyvis summary graph from anchors in tool I/O and the answer (no per-step graphs)."""
    anchors = gather_investigation_anchors(tr)
    G = get_graph()
    with st.expander("Investigation graph", expanded=True):
        hop = st.slider(
            "Neighbourhood hops (summary graph)",
            min_value=1,
            max_value=5,
            value=1,
            key=f"inv_graph_hop{key_suffix}",
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
                "No graph anchors matched the loaded graph (no `Person|…`-style ids in tool text, "
                "no raw `node_id` values from tools, and synthesis **graph_focus** is missing or not a node "
                "in `nodes.csv`). Run a question that resolves specific entities, or check the tool steps."
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


def _render_tool_planner_result(tr: ToolAgentResult, *, key_suffix: str = "") -> None:
    """Tool trace, judge rounds (internal), synthesis answer, and summary graph."""
    st.subheader("Investigation")
    if tr.error:
        st.error(tr.error)
        return
    if not tr.steps and not tr.final_text:
        st.warning("No tool steps and no answer returned.")
        return
    # 1) Tool evaluation
    st.subheader("Tool evaluation")
    pf = getattr(tr, "preflight", None)
    ex = getattr(tr, "extension_authoring", None)
    if pf or ex:
        with st.expander("Details", expanded=False):
            if pf:
                st.json(pf)
            if ex:
                st.markdown("**Extension authoring**")
                st.json(ex)
    else:
        st.caption("_(No tool evaluation info for this run.)_")

    # 2) Tool steps (all planner phases in order; no separate "Planner phase N" headings)
    st.subheader("Tool steps")
    for i, step in enumerate(tr.steps, start=1):
        preview = step.result_preview
        if len(preview) > 12000:
            preview = preview[:12000] + "\n\n…(truncated for display)…"
        with st.expander(f"Step {i}: `{step.tool}`", expanded=(i == 1 and len(tr.steps) <= 3)):
            st.json(step.input)
            st.text(preview)

    # 3) Reviewer
    st.subheader("Reviewer")
    if getattr(tr, "judge_rounds", None):
        for jr in tr.judge_rounds:
            label = "Satisfied — proceed to synthesis" if jr.satisfied else "Not satisfied — more tools"
            with st.expander(label, expanded=False):
                st.markdown(jr.rationale)
                if jr.feedback_for_planner:
                    st.text(jr.feedback_for_planner)
    else:
        st.caption("_(No reviewer rounds recorded.)_")
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
    _render_investigation_graph(tr, key_suffix=key_suffix)


def _run_with_backend(
    question: str,
    backend: str,
    *,
    progress_cb: callable | None = None,
) -> tuple[ToolAgentResult, float]:
    """Run the full investigation under a specific graph backend.

    ``backend`` is ``"networkx"``, ``"neo4j"`` (native Cypher helpers), or ``"llm_cypher"``
    (investigation LLM emits read-only Cypher per tool). Returns ``(result, elapsed_seconds)``.
    """
    import time as _time

    start = _time.time()
    if backend == "networkx":
        with force_networkx_reads():
            result = run_tool_planner_agent(question, progress_cb=progress_cb)
    elif backend == "neo4j":
        with temporary_neo4j_read_native():
            result = run_tool_planner_agent(question, progress_cb=progress_cb)
    else:
        with temporary_neo4j_read_llm_cypher():
            result = run_tool_planner_agent(question, progress_cb=progress_cb)
    return result, _time.time() - start


def _render_three_way_comparison(
    nx_result: ToolAgentResult,
    neo4j_result: ToolAgentResult,
    llm_result: ToolAgentResult,
    nx_elapsed: float,
    neo4j_elapsed: float,
    llm_elapsed: float,
) -> None:
    """Render NetworkX, Neo4j native, and LLM-authored Cypher results side-by-side."""
    c1, c2, c3 = st.columns(3, gap="large")
    with c1:
        st.markdown(
            f"## NetworkX &nbsp;&nbsp; <span style='font-size:0.8em;color:gray;'>⏱ {nx_elapsed:.1f}s</span>",
            unsafe_allow_html=True,
        )
        _render_tool_planner_result(nx_result, key_suffix="_nx3")
    with c2:
        st.markdown(
            f"## Neo4j native &nbsp;&nbsp; <span style='font-size:0.8em;color:gray;'>⏱ {neo4j_elapsed:.1f}s</span>",
            unsafe_allow_html=True,
        )
        _render_tool_planner_result(neo4j_result, key_suffix="_neo3")
    with c3:
        st.markdown(
            f"## LLM Cypher &nbsp;&nbsp; <span style='font-size:0.8em;color:gray;'>⏱ {llm_elapsed:.1f}s</span>",
            unsafe_allow_html=True,
        )
        _render_tool_planner_result(llm_result, key_suffix="_llm3")


def _render_comparison_results(
    nx_result: ToolAgentResult,
    neo4j_result: ToolAgentResult,
    nx_elapsed: float,
    neo4j_elapsed: float,
) -> None:
    """Render NetworkX and Neo4j investigation results side-by-side."""
    col_nx, col_neo = st.columns(2, gap="large")
    with col_nx:
        st.markdown(
            f"## NetworkX &nbsp;&nbsp; <span style='font-size:0.8em;color:gray;'>⏱ {nx_elapsed:.1f}s</span>",
            unsafe_allow_html=True,
        )
        _render_tool_planner_result(nx_result, key_suffix="_nx")
    with col_neo:
        st.markdown(
            f"## Neo4j Native &nbsp;&nbsp; <span style='font-size:0.8em;color:gray;'>⏱ {neo4j_elapsed:.1f}s</span>",
            unsafe_allow_html=True,
        )
        _render_tool_planner_result(neo4j_result, key_suffix="_neo4j")


def main() -> None:
    st.set_page_config(
        page_title="InvestigAI PoC v1",
        page_icon="🔎",
        layout="wide",
    )

    st.title("InvestigAI")
    st.subheader("LTC investigation copilot")
    st.markdown(
        "**Tool evaluation** checks whether the current graph tools fit your question (and may run **extension authoring** "
        "when enabled). The LLM then executes **tool steps**—real graph queries—with a **per-investigation step cap**. "
        "A **reviewer** reads the **full** tool trace for coverage; if gaps remain, planning can repeat. "
        "**Synthesis** turns the trace into the **answer** (and graph focus) below."
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
            "e.g. Who sold POL-LTC-10042, and who filed claims on that policy? | "
            "Which joint bank accounts have holders at different addresses? | "
            "What appears within two hops of claim_C9000000122?"
        ),
        height=110,
        key="free_text_question",
        help="The model picks graph tools—search, relationship catalog, claim and person queries, pattern scans—to answer your question.",
    )
    run = st.button("Run investigation", type="primary", key="run_query_btn")
    compare_all_three = st.toggle(
        "Compare all three architectures side-by-side",
        value=False,
        key="compare_all_three_toggle",
        help=(
            "One click: runs three full investigations (same question) — **NetworkX** in-memory scans, "
            "**Neo4j native** hand-written Cypher helpers, **LLM Cypher** model-authored read-only Cypher per tool. "
            "Requires Neo4j Aura, synced data, and your investigation LLM keys. Expect extra latency and API cost."
        ),
    )
    st.radio(
        "Or choose comparison detail (when the toggle is off)",
        ("Off", "NetworkX vs Neo4j native", "Three-way: + LLM-authored Cypher per tool"),
        horizontal=True,
        key="investigation_compare_mode",
        disabled=compare_all_three,
        help=(
            "Dual mode runs two investigations. Three-way adds a third path where each graph tool is implemented "
            "by asking the investigation LLM for read-only Cypher (many extra LLM calls + Aura reads)."
        ),
    )
    with st.expander("How the three graph architectures differ", expanded=False):
        st.markdown(
            """
**Shared front half (all modes)**  
The user question goes through the same **tool planner** (Gemini / Claude / Ollama): the model picks the same
**named tools** (`search_nodes`, `summarize_graph`, …), then the **coverage judge** and **synthesis** produce the answer.

**1 — NetworkX (in-memory)**  
Each tool call runs Python on an **in-memory** `networkx.DiGraph` loaded from CSV (or hydrated from Neo4j when
`GRAPH_BACKEND=neo4j`). No per-tool Cypher; graph logic is the reference implementations in `query_graph`.

**2 — Neo4j native**  
With `NEO4J_READ_MODE=native` (forced during comparison), each tool maps to **hand-written** Cypher in
`neo4j_native_reads` / `neo4j_native_heavy`, executed via `run_read_query` against Aura (`:Entity`, `:GRAPH_EDGE`).

**3 — LLM-authored Cypher**  
With `NEO4J_READ_MODE=llm_cypher` (forced for the third column), the **same** tool name and arguments are sent to the
**investigation LLM**, which returns read-only Cypher + parameters; after validation, that query runs on Aura. The planner
and tool *names* are unchanged — only the **implementation** of each step is model-generated instead of the native Python helpers.
            """.strip()
        )

    # ── Before-run entity resolution ─────────────────────────────────────────
    # State keys:
    # - er_pending_question: original user question awaiting resolution/run
    # - er_mentions: list[{mention, node_type_hint}]
    # - er_candidates: dict[mention] -> list[Candidate] (serialized as dicts)
    # - er_selections: dict[mention] -> selected node_id
    # - er_status: "idle" | "picking"
    if "er_status" not in st.session_state:
        st.session_state["er_status"] = "idle"

    def _reset_entity_resolution() -> None:
        for k in (
            "er_pending_question",
            "er_mentions",
            "er_candidates",
            "er_selections",
            "er_status",
        ):
            if k in st.session_state:
                del st.session_state[k]
        st.session_state["er_status"] = "idle"

    if run:
        q = (question or "").strip()
        if not q:
            st.warning("Enter a question, then click **Run investigation**.")
        else:
            # If the question already contains node ids, skip entity resolution.
            if question_already_has_node_ids(q):
                st.session_state["er_status"] = "idle"
                st.session_state["er_pending_question"] = q
            else:
                st.session_state["er_pending_question"] = q
                st.session_state["er_status"] = "picking"

                # Streamlit hot-reload can race module updates. Avoid `from ... import name`
                # so missing attributes don't crash the run.
                try:
                    from src.llm import entity_resolution as _er  # type: ignore
                except Exception as exc:
                    _er = None
                    mentions = []
                    mention_dbg = {
                        "backend": "",
                        "raw_preview": "",
                        "error": f"import_failed: {type(exc).__name__}: {exc}",
                    }
                else:
                    fn = getattr(_er, "extract_entity_mentions_with_debug", None)
                    if callable(fn):
                        mentions, mention_dbg = fn(q)
                    else:
                        # Fall back to non-debug extractor if only that is available.
                        fn2 = getattr(_er, "extract_entity_mentions", None)
                        mentions = fn2(q) if callable(fn2) else []
                        mention_dbg = {
                            "backend": "",
                            "raw_preview": "",
                            "error": "extract_entity_mentions_with_debug_missing",
                        }
                if not mentions:
                    mentions = fallback_mentions(q)
                st.session_state["er_mentions"] = mentions

                # Build candidates + auto-select singletons.
                selections: dict[str, str] = {}
                cand_map: dict[str, list[dict]] = {}
                unmapped: list[str] = []
                any_ambiguous = False
                for m in mentions[:5]:
                    mention_raw = str(m.get("mention", "")).strip()
                    if not mention_raw:
                        continue
                    # Map to the exact substring in the user's question (case/punctuation-insensitive).
                    span = locate_mention_span(q, mention_raw)
                    if span is None:
                        # Still allow disambiguation even if we can't find an exact substring to replace.
                        mention = mention_raw
                        unmapped.append(mention_raw)
                    else:
                        mention = q[span[0] : span[1]]
                    hint = m.get("node_type_hint")
                    hint_s = str(hint).strip() if hint is not None else None
                    cands = candidate_nodes(mention=mention, node_type_hint=hint_s, limit=25)
                    if not cands:
                        continue
                    cand_map[mention] = [c.__dict__ for c in cands]
                    if len(cands) == 1:
                        selections[mention] = cands[0].node_id
                    else:
                        any_ambiguous = True
                st.session_state["er_candidates"] = cand_map
                st.session_state["er_selections"] = selections
                st.session_state["er_unmapped_mentions"] = unmapped
                st.session_state["er_debug"] = {
                    "mentions": mentions,
                    "mention_extractor_debug": mention_dbg,
                    "candidate_counts": {k: len(v or []) for k, v in cand_map.items()},
                    "unmapped_mentions": unmapped,
                    "any_ambiguous": any_ambiguous,
                }

                if not cand_map or not any_ambiguous:
                    # Nothing to disambiguate (or only singletons) — run immediately.
                    st.session_state["er_status"] = "idle"

    # Render picker UI when needed.
    if st.session_state.get("er_status") == "picking":
        pending_q = str(st.session_state.get("er_pending_question") or "").strip()
        cand_map = st.session_state.get("er_candidates") or {}
        if pending_q and cand_map:
            st.info("Ambiguous entities detected. Pick the intended node(s) before running.")
            with st.form("entity_resolution_form", clear_on_submit=False):
                picks: dict[str, str] = dict(st.session_state.get("er_selections") or {})
                for mention, cands_raw in cand_map.items():
                    cands = []
                    for r in cands_raw:
                        try:
                            from src.app.entity_resolution import Candidate

                            cands.append(Candidate(**r))
                        except Exception:
                            continue
                    if not cands:
                        continue
                    if len(cands) == 1:
                        picks[mention] = cands[0].node_id
                        continue
                    default_idx = 0
                    label = f"“{mention}”"
                    chosen = st.selectbox(
                        label,
                        options=cands,
                        index=default_idx,
                        format_func=format_candidate_option,
                        key=f"pick::{mention}",
                    )
                    picks[mention] = getattr(chosen, "node_id", "") or ""

                resolved = rewrite_question(pending_q, picks)
                unmapped = st.session_state.get("er_unmapped_mentions") or []
                extra = {k: v for k, v in picks.items() if k in unmapped}
                if extra:
                    # If we couldn't locate the mention substring in the question, append the resolution
                    # so the planner still gets the chosen node ids.
                    lines = "\n".join(f"- {k}: {v}" for k, v in extra.items())
                    resolved = resolved.rstrip() + "\n\nResolved entities:\n" + lines
                st.caption("Resolved question (preview)")
                st.code(resolved, language=None)

                # Validate that selected node ids exist in the currently loaded graph.
                G = get_graph()
                invalid = sorted({v for v in picks.values() if v and v not in G})
                if invalid:
                    st.error(
                        "One or more selected node ids are not in the loaded graph. "
                        "This can happen if the dataset was rebuilt/reloaded since candidates were generated.\n\n"
                        + "\n".join(f"- `{x}`" for x in invalid)
                    )
                c1, c2 = st.columns(2)
                with c1:
                    submit = st.form_submit_button(
                        "Run with selections", type="primary", disabled=bool(invalid)
                    )
                with c2:
                    cancel = st.form_submit_button("Cancel")

            if cancel:
                _reset_entity_resolution()
                st.stop()
            if submit:
                st.session_state["er_status"] = "idle"
                st.session_state["er_pending_question"] = resolved
        else:
            _reset_entity_resolution()

    compare_all_three = bool(st.session_state.get("compare_all_three_toggle", False))
    if compare_all_three:
        _compare_mode_active = True
        _triple_compare = True
        _cmp = "Three-way (toggle)"
    else:
        _cmp = str(st.session_state.get("investigation_compare_mode", "Off") or "Off")
        _compare_mode_active = _cmp != "Off"
        _triple_compare = _cmp.startswith("Three")

    # If we have a pending (possibly rewritten) question and we're idle, run now.
    if st.session_state.get("er_status") == "idle" and st.session_state.get("er_pending_question"):
        q_to_run = str(st.session_state.get("er_pending_question") or "").strip()
        # Clear pending question immediately to avoid re-running on Streamlit reruns.
        st.session_state["er_pending_question"] = ""
        if q_to_run:
            if _compare_mode_active:
                # ── Compare mode: run NetworkX, Neo4j native, and (optionally) LLM Cypher ─
                def _make_progress_cb(label: str, status_el: "st.delta_generator.DeltaGenerator", recent_el: "st.delta_generator.DeltaGenerator") -> callable:  # type: ignore[name-defined]
                    _phase_start = [time.time()]
                    _events: list[str] = []

                    def _cb(ev: dict) -> None:
                        et = str(ev.get("type", "")).strip()
                        msg = str(ev.get("message", "")).strip()
                        if not msg:
                            if et == "tool_start":
                                msg = f"Running tool: `{ev.get('tool')}`…"
                            elif et == "tool_done":
                                msg = f"Tool complete: `{ev.get('tool')}`"
                            else:
                                msg = et or "Working…"
                        elapsed = int(time.time() - _phase_start[0])
                        status_el.markdown(f"**{label}** — {msg}  \n_(elapsed: {elapsed}s)_")
                        _events.append(msg)
                        recent_el.markdown(
                            f"**{label} — recent activity**\n\n"
                            + "\n".join(f"- {t}" for t in _events[-6:])
                        )

                    return _cb

                try:
                    st.info("Running **NetworkX** investigation…")
                    nx_status = st.empty()
                    nx_recent = st.empty()
                    with st.spinner("NetworkX — working…"):
                        nx_result, nx_elapsed = _run_with_backend(
                            q_to_run,
                            "networkx",
                            progress_cb=_make_progress_cb("NetworkX", nx_status, nx_recent),
                        )
                    nx_status.empty()
                    nx_recent.empty()

                    st.info("Running **Neo4j native** investigation…")
                    neo_status = st.empty()
                    neo_recent = st.empty()
                    with st.spinner("Neo4j native — working…"):
                        neo4j_result, neo4j_elapsed = _run_with_backend(
                            q_to_run,
                            "neo4j",
                            progress_cb=_make_progress_cb("Neo4j native", neo_status, neo_recent),
                        )
                    neo_status.empty()
                    neo_recent.empty()

                    payload: dict = {
                        "triple": bool(_triple_compare),
                        "nx_result": nx_result,
                        "neo4j_result": neo4j_result,
                        "nx_elapsed": nx_elapsed,
                        "neo4j_elapsed": neo4j_elapsed,
                    }
                    if _triple_compare:
                        st.info("Running **LLM-authored Cypher** investigation (extra LLM call per tool)…")
                        llm_status = st.empty()
                        llm_recent = st.empty()
                        with st.spinner("LLM Cypher — working…"):
                            llm_result, llm_elapsed = _run_with_backend(
                                q_to_run,
                                "llm_cypher",
                                progress_cb=_make_progress_cb("LLM Cypher", llm_status, llm_recent),
                            )
                        llm_status.empty()
                        llm_recent.empty()
                        payload["llm_cypher_result"] = llm_result
                        payload["llm_cypher_elapsed"] = llm_elapsed
                    st.session_state["last_compare_run"] = payload
                    # Clear any previous single-backend result so we only render the comparison.
                    st.session_state.pop("last_tool_run", None)
                except Exception as exc:
                    st.error("Comparison run failed — see details below.")
                    st.exception(exc)
            else:
                # ── Single-backend mode (existing behaviour) ─────────────────────────
                try:
                    status = st.empty()
                    recent = st.empty()
                    start = time.time()
                    events: list[str] = []

                    def _progress_cb(ev: dict) -> None:
                        et = str(ev.get("type", "")).strip()
                        msg = str(ev.get("message", "")).strip()
                        if not msg:
                            if et == "tool_start":
                                msg = f"Running tool: `{ev.get('tool')}`…"
                            elif et == "tool_done":
                                msg = f"Tool complete: `{ev.get('tool')}`"
                            else:
                                msg = et or "Working…"
                        elapsed = int(time.time() - start)
                        status.markdown(f"**Working…** {msg}  \n_(elapsed: {elapsed}s)_")
                        events.append(msg)
                        tail = events[-6:]
                        recent.markdown("**Recent activity**\n\n" + "\n".join(f"- {t}" for t in tail))

                    with st.spinner("Working…"):
                        st.session_state["last_tool_run"] = run_tool_planner_agent(q_to_run, progress_cb=_progress_cb)
                    # Clear any previous comparison result.
                    st.session_state.pop("last_compare_run", None)
                except Exception as exc:
                    st.error("Run failed — see details below.")
                    st.exception(exc)

    compare_run = st.session_state.get("last_compare_run")
    last = st.session_state.get("last_tool_run")
    if compare_run:
        st.divider()
        if compare_run.get("triple"):
            st.markdown(
                f"**Three-way comparison** — NetworkX **{compare_run['nx_elapsed']:.1f}s**, "
                f"Neo4j native **{compare_run['neo4j_elapsed']:.1f}s**, "
                f"LLM Cypher **{compare_run.get('llm_cypher_elapsed', 0):.1f}s**."
            )
            _render_three_way_comparison(
                compare_run["nx_result"],
                compare_run["neo4j_result"],
                compare_run["llm_cypher_result"],
                compare_run["nx_elapsed"],
                compare_run["neo4j_elapsed"],
                float(compare_run.get("llm_cypher_elapsed") or 0),
            )
        else:
            st.markdown(
                f"**Comparison run** — NetworkX finished in **{compare_run['nx_elapsed']:.1f}s**, "
                f"Neo4j finished in **{compare_run['neo4j_elapsed']:.1f}s** "
                f"({compare_run['neo4j_elapsed'] / compare_run['nx_elapsed']:.2f}× relative)."
                if compare_run["nx_elapsed"] > 0
                else "**Comparison run complete.**"
            )
            _render_comparison_results(
                compare_run["nx_result"],
                compare_run["neo4j_result"],
                compare_run["nx_elapsed"],
                compare_run["neo4j_elapsed"],
            )
    elif last is not None:
        _render_tool_planner_result(last)
    elif not question:
        st.caption("Type a question and click **Run investigation**.")


if __name__ == "__main__":
    main()
