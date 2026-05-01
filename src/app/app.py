"""
InvestigAI PoC v1 — Streamlit UI.

Loads the graph from ``data/processed/*.csv`` (via ``query_graph``). Multi-turn
**session memory** (``src/session/``) rewrites or clarifies follow-ups before the
same **tool-planner** → **coverage judge** (full tool trace, uncapped outer loop) →
**synthesis** pipeline runs. Set ``INVESTIGATION_LLM`` to ``gemini`` (``GEMINI_API_KEY``),
``anthropic`` (``ANTHROPIC_API_KEY``), or ``ollama`` (local Ollama; see README).

How to run (from the **project root**, the folder that contains ``src/``)::

    streamlit run src/app/app.py

If Streamlit cannot import ``src``, set PYTHONPATH to the project root::

    PYTHONPATH=. streamlit run src/app/app.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
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
from src.app.ui_theme import inject_main_page_theme, section_label  # noqa: E402
from src.app.investigation_graph import (  # noqa: E402
    compute_summary_visible_nodes,
    gather_investigation_anchors,
)
from src.app.entity_resolution import (  # noqa: E402
    append_verified_graph_node_hint,
    candidate_nodes,
    fallback_mentions,
    filter_mentions_excluding_graph_anchors,
    format_candidate_option,
    locate_mention_span,
    rewrite_question,
    unresolved_graph_like_id_tokens,
    verified_graph_anchor_spans,
)
from src.graph_query.query_graph import get_graph, load_graph, summarize_graph  # noqa: E402
from src.llm.tool_agent import ToolAgentResult, run_tool_planner_agent  # noqa: E402
from src.session.context_resolver import resolve_question_with_session_memory  # noqa: E402
from src.session.memory import build_turn_from_result, merge_session_referents, serialize_turn  # noqa: E402
from src.session.report import build_session_report_html, summarize_answer_bullets  # noqa: E402


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
    hop = st.slider(
        "Neighbourhood hops",
        min_value=1,
        max_value=5,
        value=1,
        key="inv_graph_hop",
        help=(
            "Centers on synthesis graph focus when set, otherwise anchors from the run; "
            "includes nodes within this many undirected hops. Does not re-run the LLM."
        ),
    )
    visible, focus, _mode, edge_filter, slice_hint = compute_summary_visible_nodes(
        G, tr, anchors, hop_depth=hop
    )
    if not visible:
        st.caption(
            "No graph anchors matched the loaded graph (no Person-style ids in tool text, "
            "no raw node_id values from tools, and synthesis graph_focus is missing or invalid). "
            "Try a question that resolves specific entities, or inspect tool steps below."
        )
        return
    if slice_hint:
        st.caption(slice_hint)
    st.caption(
        f"{len(visible)} nodes · {len({a for a in anchors if a in G})} anchor(s) · hop {hop}."
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
    """Outcome-first: answer and graph, then reviewer, tool evaluation, tool steps."""
    if tr.error:
        st.error(tr.error)
        return
    if not tr.steps and not tr.final_text:
        st.warning("No tool steps and no answer returned.")
        return

    with st.container(border=True):
        st.markdown("### Answer")
        bullets = summarize_answer_bullets(tr.final_text or "", max_bullets=5)
        if bullets:
            st.caption("Key findings")
            st.markdown("\n".join(f"- {b}" for b in bullets))
        if tr.final_text:
            st.markdown(tr.final_text)
        else:
            st.caption("No synthesis answer — see tool steps below.")
        if getattr(tr, "synthesis_rationale", ""):
            st.caption(f"Graph focus rationale: {tr.synthesis_rationale}")
        if getattr(tr, "graph_focus_node_id", None):
            st.caption(f"Synthesis graph focus: `{tr.graph_focus_node_id}`")
        st.markdown("### Investigation graph")
        _render_investigation_graph(tr)

    st.markdown("### Reviewer")
    if getattr(tr, "judge_rounds", None):
        for jr in tr.judge_rounds:
            label = "Satisfied — proceed to synthesis" if jr.satisfied else "Not satisfied — more tools"
            with st.expander(label, expanded=False):
                st.markdown(jr.rationale)
                if jr.feedback_for_planner:
                    st.text(jr.feedback_for_planner)
    else:
        st.caption("No reviewer rounds recorded.")

    st.markdown("### Tool evaluation")
    pf = getattr(tr, "preflight", None)
    ex = getattr(tr, "extension_authoring", None)
    if pf or ex:
        with st.expander("Preflight and extensions", expanded=False):
            if pf:
                st.json(pf)
            if ex:
                st.markdown("**Extension authoring**")
                st.json(ex)
    else:
        st.caption("No tool evaluation details for this run.")

    st.markdown("### Tool steps")
    for i, step in enumerate(tr.steps, start=1):
        preview = step.result_preview
        if len(preview) > 12000:
            preview = preview[:12000] + "\n\n…(truncated for display)…"
        with st.expander(f"Step {i}: `{step.tool}`", expanded=False):
            st.json(step.input)
            st.text(preview)


def _render_session_history(turns: list[dict]) -> None:
    if not turns:
        st.caption("No turns in this session yet.")
        return
    for row in reversed(turns):
        turn_id = row.get("turn_id", "?")
        uq = str(row.get("user_question", "")).strip()
        iq = str(row.get("investigation_question", "")).strip()
        ans = str(row.get("final_answer", "")).strip()
        with st.expander(f"Turn {turn_id}: {uq[:90] or '(empty question)'}", expanded=False):
            st.markdown(f"**User question**\n\n{uq or '_None_'}")
            if iq and iq != uq:
                st.markdown(f"**Resolved investigation question**\n\n{iq}")
            if ans:
                st.markdown("**Answer**")
                st.markdown(ans)
            focus = row.get("graph_focus_node_id")
            if focus:
                st.caption(f"Graph focus: `{focus}`")
            anchors = row.get("anchors") or []
            if anchors:
                st.caption("Anchors: " + ", ".join(f"`{x}`" for x in anchors[:8]))


def main() -> None:
    st.set_page_config(
        page_title="InvestigAI PoC v1",
        page_icon="🔎",
        layout="wide",
    )
    inject_main_page_theme()

    st.title("InvestigAI")
    st.caption("LTC investigation copilot — session memory and graph tools; planner → judge → synthesis unchanged.")
    with st.expander("How investigations run", expanded=False):
        st.markdown(
            "**Tool evaluation** checks whether the current graph tools fit your question (and may run **extension authoring** "
            "when enabled). The LLM then executes **tool steps**—real graph queries—with a **per-investigation step cap**. "
            "A **reviewer** reads the **full** tool trace for coverage; if gaps remain, planning can repeat. "
            "**Synthesis** turns the trace into the **answer** (and graph focus) for this page."
        )

    try:
        _ensure_graph_loaded()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    if "session_turns" not in st.session_state:
        st.session_state["session_turns"] = []
    if "ctx_status" not in st.session_state:
        st.session_state["ctx_status"] = "idle"
    if "ctx_last_decision" not in st.session_state:
        st.session_state["ctx_last_decision"] = None
    if "session_active_referents" not in st.session_state:
        st.session_state["session_active_referents"] = {}
    if "er_status" not in st.session_state:
        st.session_state["er_status"] = "idle"

    summary = summarize_graph()
    m1, m2, m3 = st.columns(3)
    m1.metric("Nodes", summary["num_nodes"])
    m2.metric("Edges", summary["num_edges"])
    m3.metric("Directed", "yes" if summary["is_directed"] else "no")

    section_label("Session")
    turns_for_ui = st.session_state.get("session_turns") or []
    _render_session_history(turns_for_ui)
    s1, s2 = st.columns(2)
    with s1:
        report_html = build_session_report_html(turns_for_ui)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        st.download_button(
            "Export session report (HTML)",
            data=report_html.encode("utf-8"),
            file_name=f"investigai_session_report_{stamp}.html",
            mime="text/html",
            disabled=not bool(turns_for_ui),
            use_container_width=True,
        )
    with s2:
        if st.button("Clear session memory", type="secondary", use_container_width=True):
            st.session_state["session_turns"] = []
            st.session_state["session_active_referents"] = {}
            st.session_state["ctx_last_decision"] = None
            st.session_state["ctx_status"] = "idle"
            st.toast("Session memory cleared.", icon="✓")

    section_label("Investigate")
    with st.container(border=True):
        st.caption("Your question")
        question = st.text_area(
            "Your question",
            placeholder=(
                "e.g. Who sold POL-LTC-10042, and who filed claims on that policy? | "
                "Which joint bank accounts have holders at different addresses? | "
                "What appears within two hops of claim_C9000000122?"
            ),
            height=120,
            key="free_text_question",
            label_visibility="collapsed",
            help="The model picks graph tools—search, relationship catalog, claim and person queries, pattern scans.",
        )
        _, run_col = st.columns([5, 1])
        with run_col:
            run = st.button(
                "Run investigation",
                type="primary",
                key="run_query_btn",
                use_container_width=True,
            )

    # ── Before-run entity resolution ─────────────────────────────────────────
    # State keys:
    # - er_pending_question: question string to send to planner after resolver + ER (may differ from raw user text)
    # - er_mentions: list[{mention, node_type_hint}]
    # - er_candidates: dict[mention] -> list[Candidate] (serialized as dicts)
    # - er_selections: dict[mention] -> selected node_id
    # - er_status: "idle" | "picking"
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
            turns = st.session_state.get("session_turns") or []
            decision = resolve_question_with_session_memory(
                q,
                turns,
                session_referents=st.session_state.get("session_active_referents") or {},
            )
            st.session_state["ctx_last_decision"] = {
                "action": decision.action,
                "rationale": decision.rationale,
                "resolved_question": decision.resolved_question,
                "clarification_prompt": decision.clarification_prompt,
                "used_llm_fallback": decision.used_llm_fallback,
            }
            if decision.action == "clarify":
                st.session_state["ctx_status"] = "clarify"
                st.session_state["ctx_pending_question"] = q
                st.session_state["ctx_pending_resolved_question"] = decision.resolved_question
                st.session_state["ctx_clarification_prompt"] = decision.clarification_prompt
            else:
                st.session_state["ctx_status"] = "idle"
                q_for_er = (decision.resolved_question or q).strip()
                st.session_state["ctx_pending_question"] = q
                st.session_state["ctx_pending_resolved_question"] = q_for_er
                st.session_state["er_pending_question"] = q_for_er
                st.session_state["er_status"] = "picking"

                # Streamlit hot-reload can race module updates. Avoid `from ... import name`
                # so missing attributes don't crash the run.
                try:
                    from src.llm import entity_resolution as _er  # type: ignore
                except Exception as exc:
                    _er = None
                    mentions = []
                else:
                    fn = getattr(_er, "extract_entity_mentions_with_debug", None)
                    if callable(fn):
                        mentions, _ = fn(q_for_er)
                    else:
                        # Fall back to non-debug extractor if only that is available.
                        fn2 = getattr(_er, "extract_entity_mentions", None)
                        mentions = fn2(q_for_er) if callable(fn2) else []
                if not mentions:
                    mentions = fallback_mentions(q_for_er)
                G_er = get_graph()
                mentions = filter_mentions_excluding_graph_anchors(q_for_er, mentions, G_er)
                orphan_ids = unresolved_graph_like_id_tokens(q_for_er, G_er)
                if orphan_ids:
                    st.warning(
                        "These tokens look like graph node ids but are **not** in the loaded graph: "
                        + ", ".join(f"`{x}`" for x in orphan_ids)
                    )
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
                    span = locate_mention_span(q_for_er, mention_raw)
                    if span is None:
                        # Still allow disambiguation even if we can't find an exact substring to replace.
                        mention = mention_raw
                        unmapped.append(mention_raw)
                    else:
                        mention = q_for_er[span[0] : span[1]]
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

                if not cand_map or not any_ambiguous:
                    # Nothing to disambiguate (or only singletons) — run immediately.
                    st.session_state["er_status"] = "idle"

    if st.session_state.get("ctx_status") == "clarify":
        prompt = str(st.session_state.get("ctx_clarification_prompt") or "").strip()
        if not prompt:
            prompt = "Please clarify what entity or result from earlier turns this follow-up refers to."
        st.warning(prompt)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Run as typed", key="ctx_run_as_typed", type="primary"):
                st.session_state["er_status"] = "idle"
                st.session_state["er_pending_question"] = str(st.session_state.get("ctx_pending_question") or "").strip()
                st.session_state["ctx_status"] = "idle"
        with c2:
            if st.button("Cancel", key="ctx_cancel"):
                st.session_state["ctx_status"] = "idle"
                st.session_state["ctx_pending_question"] = ""
                st.session_state["ctx_pending_resolved_question"] = ""
                st.stop()

    last_decision = st.session_state.get("ctx_last_decision")
    if isinstance(last_decision, dict):
        action = str(last_decision.get("action", "pass_through"))
        rationale = str(last_decision.get("rationale", "")).strip()
        resolved_q = str(last_decision.get("resolved_question", "")).strip()
        if action == "rewrite" and resolved_q:
            st.caption("Session context resolver rewrote your question for this turn.")
            with st.expander("Resolved question preview", expanded=False):
                st.code(resolved_q, language=None)
        if rationale:
            st.caption(f"Context resolver rationale: {rationale}")

    # Render picker UI when needed.
    if st.session_state.get("er_status") == "picking":
        pending_q = str(st.session_state.get("er_pending_question") or "").strip()
        cand_map = st.session_state.get("er_candidates") or {}
        if pending_q and cand_map:
            with st.container(border=True):
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

    # If we have a pending (possibly rewritten) question and we're idle, run now.
    if st.session_state.get("er_status") == "idle" and st.session_state.get("er_pending_question"):
        q_to_run = str(st.session_state.get("er_pending_question") or "").strip()
        # Clear pending question immediately to avoid re-running on Streamlit reruns.
        st.session_state["er_pending_question"] = ""
        if q_to_run:
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
                    q_planner = append_verified_graph_node_hint(q_to_run, get_graph())
                    tr = run_tool_planner_agent(q_planner, progress_cb=_progress_cb)
                    st.session_state["last_tool_run"] = tr
                    turn_id = len(st.session_state.get("session_turns") or []) + 1
                    user_q = str(st.session_state.get("ctx_pending_question") or q_to_run).strip()
                    turn = build_turn_from_result(
                        turn_id=turn_id,
                        user_question=user_q,
                        investigation_question=q_to_run,
                        result=tr,
                    )
                    turns = list(st.session_state.get("session_turns") or [])
                    row = serialize_turn(turn)
                    turns.append(row)
                    st.session_state["session_turns"] = turns[-30:]
                    st.session_state["session_active_referents"] = merge_session_referents(
                        st.session_state.get("session_active_referents"),
                        row.get("active_referents") or {},
                    )
                # Session history + export are rendered above this block; without a rerun they would
                # still reflect pre-run state for this script execution. Rerun once so the new turn
                # appears in history and the download button is built from updated session_turns.
                st.rerun()
            except Exception as exc:
                st.error("Run failed — see details below.")
                st.exception(exc)

    last = st.session_state.get("last_tool_run")
    if last is not None:
        _render_tool_planner_result(last)
    elif not (question or "").strip():
        st.caption("Enter a question above, then run an investigation to see results here.")


if __name__ == "__main__":
    main()
