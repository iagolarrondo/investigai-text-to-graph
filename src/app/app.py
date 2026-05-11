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
from src.app.ui_theme import inject_main_page_theme, section_label  # noqa: E402
from src.app.investigation_graph import (  # noqa: E402
    compute_summary_visible_nodes,
    gather_investigation_anchors,
)
from src.app.entity_resolution import (  # noqa: E402
    append_verified_graph_node_hint,
    candidate_nodes,
    collect_er_candidate_node_ids,
    collect_er_priority_node_ids,
    fallback_mentions,
    filter_mentions_excluding_graph_anchors,
    format_candidate_option,
    locate_mention_span,
    rewrite_question,
    unresolved_graph_like_id_tokens,
)
from src.graph_query.native_read_mode import (
    force_networkx_reads,
    neo4j_llm_cypher_reads_enabled,
    neo4j_native_reads_enabled,
    temporary_neo4j_read_llm_cypher,
    temporary_neo4j_read_native,
)  # noqa: E402
from src.graph_query.query_graph import get_graph, load_graph, summarize_graph  # noqa: E402
from src.llm.tool_agent import ToolAgentResult, run_tool_planner_agent  # noqa: E402
from src.session.context_resolver import resolve_question_with_session_memory  # noqa: E402
from src.session.memory import (  # noqa: E402
    build_turn_from_result,
    extend_referents_with_node_ids,
    merge_session_referents,
    serialize_turn,
)
from src.session.node_id_canonical import canonicalize_referents_dict  # noqa: E402
from src.session.report import build_session_report_html, summarize_answer_bullets  # noqa: E402


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
    hop = st.slider(
        "Neighbourhood hops",
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


def _render_tool_planner_result(tr: ToolAgentResult, *, key_suffix: str = "") -> None:
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
        _render_investigation_graph(tr, key_suffix=key_suffix)

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


def _run_with_backend(
    question: str,
    backend: str,
    *,
    progress_cb: callable | None = None,
) -> tuple[ToolAgentResult, float]:
    """Run the full investigation under a specific graph backend.

    ``backend`` is ``"networkx"``, ``"neo4j"`` (native Cypher helpers), or ``"llm_cypher"``
    (tool-free Cypher planner: read-only Cypher JSON in a chat loop, no named tools). Returns ``(result, elapsed_seconds)``.
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


def _render_compare_runs(runs: list[dict]) -> None:
    """Render N compare runs side-by-side. Each entry: {id,label,result,elapsed}."""
    if not runs:
        return
    cols = st.columns(len(runs), gap="large")
    for col, run in zip(cols, runs):
        label = run.get("label", run.get("id", "Backend"))
        elapsed = float(run.get("elapsed") or 0)
        key_suffix = f"_cmp_{run.get('id', label)}"
        with col:
            st.markdown(
                f"## {label} &nbsp;&nbsp; <span style='font-size:0.8em;color:gray;'>⏱ {elapsed:.1f}s</span>",
                unsafe_allow_html=True,
            )
            _render_tool_planner_result(run["result"], key_suffix=key_suffix)


def main() -> None:
    st.set_page_config(
        page_title="InvestigAI PoC v1",
        page_icon="🔎",
        layout="wide",
    )
    inject_main_page_theme()

    st.title("InvestigAI")
    with st.expander("How investigations are run", expanded=False):
        st.markdown(
            """
### Modes

- **Investigate** (below): run **one** backend (**Single model**) or **compare** the same question across several (**Multiple model comparison**).
- **Single model** choices, in short: **in-memory Python graph**, **Neo4j using fixed queries**, or **Neo4j where the model writes its own read-only queries**.
- For deeper differences, open **How the three graph architectures differ** under Investigate.
- **Comparison** runs don’t add to session history or the downloadable session report.

### Session memory

- Previous answers stay in **Session** so follow-ups can refer back.
- The app may **rephrase** vague follow-ups or **ask you to clarify** what you mean.
- If a name could match several people or places, you may see a **picker** before the run starts.
- Use **Clear session memory** to start fresh; **Export session report** saves what ran.

### What happens when you run

- The model **explores the graph**, then a **review step** checks whether the question was answered, then a **final answer** (and graph highlight) is produced.
            """.strip()
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

    # Header metrics: in-memory graph only (CSV or Neo4j-hydrated), not a live Aura summarize.
    # Avoids crashing the app when NEO4J_READ_MODE=native but routing fails (VPN/DNS).
    with force_networkx_reads():
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
        run_mode = st.radio(
            "Single model or multiple model comparison",
            ("Single model", "Multiple model comparison"),
            index=0,
            horizontal=True,
            key="investigation_run_mode",
            help=(
                "**Single model** runs the investigation on one graph backend. "
                "**Multiple model comparison** runs the same question against 2+ backends side-by-side."
            ),
        )
        _BACKEND_OPTIONS = [
            "NetworkX (Dynamic Python)",
            "Neo4j (NetworkX functions translated to Cypher)",
            "Neo4j (tool-free Cypher planner)",
        ]
        if run_mode == "Single model":
            st.pills(
                "Model",
                options=_BACKEND_OPTIONS,
                selection_mode="single",
                default="NetworkX (Dynamic Python)",
                key="investigation_single_backend",
                help=(
                    "- **NetworkX (Dynamic Python)** — in-memory Python on a NetworkX DiGraph (default, no DB).\n"
                    "- **Neo4j (NetworkX functions translated to Cypher)** — engineer-written Cypher of the same tools, running on Aura.\n"
                    "- **Neo4j (tool-free Cypher planner)** — no named graph tools: the investigation LLM emits read-only Cypher as JSON in a chat loop, validated and executed on Aura."
                ),
            )
        else:
            st.pills(
                "Models to compare (click to toggle)",
                options=_BACKEND_OPTIONS,
                selection_mode="multi",
                default=_BACKEND_OPTIONS,
                key="investigation_compare_backends",
                help=(
                    "Click each model to include / exclude it. At least 2 must be selected. "
                    "Both Neo4j backends need Aura + synced data; the tool-free Cypher planner uses the investigation LLM each planner round (no provider tool API)."
                ),
            )
        with st.expander("How the three graph architectures differ", expanded=False):
            st.markdown(
                """
**Shared front half (all modes)**  
The user question goes through an **investigation LLM** (Gemini / Claude / Ollama), then the **coverage judge** and **synthesis** produce the answer. In **native** and **NetworkX** modes the model uses **named graph tools**; in **llm_cypher** mode there are **no provider tools** — only a Cypher JSON chat loop (see column 3).

**1 — NetworkX (Dynamic Python)**
Each tool call runs Python on an **in-memory** `networkx.DiGraph` loaded from CSV (or hydrated from Neo4j when
`GRAPH_BACKEND=neo4j`). No DB queries; graph logic is the reference implementations in `query_graph`.

**2 — Neo4j (NetworkX functions translated to Cypher)**
With `NEO4J_READ_MODE=native` (forced during comparison), each tool maps to **engineer-written** Cypher in
`neo4j_native_reads` / `neo4j_native_heavy` — same inputs and outputs as the NetworkX functions, but the traversal is
expressed as Cypher and executed by Aura (`:Entity`, `:GRAPH_EDGE`).

**3 — Neo4j (tool-free Cypher planner)**
With `NEO4J_READ_MODE=llm_cypher` (forced for the third column), the investigation LLM **does not** receive named graph tools.
It runs a multi-turn chat where each turn outputs strict JSON (`done`, optional `cypher` + `params`, optional `planner_note`);
queries are validated as read-only and executed on Aura. Trace rows still appear as investigation steps for the judge (synthetic step type `__cypher__`).
                """.strip()
            )
        _, run_col = st.columns([4, 2])
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

                    # Validate against the active graph read path before submitting the form.
                    if neo4j_native_reads_enabled() or neo4j_llm_cypher_reads_enabled():
                        from src.graph_query import neo4j_native_reads as nnr

                        invalid = sorted({v for v in picks.values() if v and not nnr.entity_exists(v)})
                    else:
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

    _BACKEND_LABEL_TO_ID = {
        "NetworkX (Dynamic Python)": "networkx",
        "Neo4j (NetworkX functions translated to Cypher)": "neo4j",
        "Neo4j (tool-free Cypher planner)": "llm_cypher",
    }
    _run_mode = str(
        st.session_state.get("investigation_run_mode") or "Single model"
    )
    if _run_mode == "Multiple model comparison":
        _selected_compare_labels = list(
            st.session_state.get("investigation_compare_backends") or []
        )
        _compare_backends = [
            (_BACKEND_LABEL_TO_ID[lbl], lbl)
            for lbl in _selected_compare_labels
            if lbl in _BACKEND_LABEL_TO_ID
        ]
        _compare_mode_active = len(_compare_backends) >= 2
        _single_backend_id = None
    else:
        _compare_mode_active = False
        _compare_backends = []
        _single_label = str(
            st.session_state.get("investigation_single_backend")
            or "NetworkX (Dynamic Python)"
        )
        _single_backend_id = _BACKEND_LABEL_TO_ID.get(_single_label, "networkx")

    # If we have a pending (possibly rewritten) question and we're idle, run now.
    if st.session_state.get("er_status") == "idle" and st.session_state.get("er_pending_question"):
        q_to_run = str(st.session_state.get("er_pending_question") or "").strip()
        # Clear pending question immediately to avoid re-running on Streamlit reruns.
        st.session_state["er_pending_question"] = ""
        if q_to_run:
            if _compare_mode_active:
                # ── Compare mode: run the selected backends sequentially ─────────
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
                    runs: list[dict] = []
                    for backend_id, backend_label in _compare_backends:
                        st.info(f"Running **{backend_label}** investigation…")
                        s_el = st.empty()
                        r_el = st.empty()
                        with st.spinner(f"{backend_label} — working…"):
                            result, elapsed = _run_with_backend(
                                q_to_run,
                                backend_id,
                                progress_cb=_make_progress_cb(backend_label, s_el, r_el),
                            )
                        s_el.empty()
                        r_el.empty()
                        runs.append(
                            {
                                "id": backend_id,
                                "label": backend_label,
                                "result": result,
                                "elapsed": elapsed,
                            }
                        )
                    st.session_state["last_compare_run"] = {"runs": runs}
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
                        q_planner = append_verified_graph_node_hint(q_to_run, get_graph())
                        if _single_backend_id == "networkx":
                            with force_networkx_reads():
                                tr = run_tool_planner_agent(q_planner, progress_cb=_progress_cb)
                        elif _single_backend_id == "neo4j":
                            with temporary_neo4j_read_native():
                                tr = run_tool_planner_agent(q_planner, progress_cb=_progress_cb)
                        elif _single_backend_id == "llm_cypher":
                            with temporary_neo4j_read_llm_cypher():
                                tr = run_tool_planner_agent(q_planner, progress_cb=_progress_cb)
                        else:
                            tr = run_tool_planner_agent(q_planner, progress_cb=_progress_cb)
                    status.empty()
                    recent.empty()
                    st.session_state["last_tool_run"] = tr
                    st.session_state.pop("last_compare_run", None)
                    turn_id = len(st.session_state.get("session_turns") or []) + 1
                    user_q = str(st.session_state.get("ctx_pending_question") or q_to_run).strip()
                    turn = build_turn_from_result(
                        turn_id=turn_id,
                        user_question=user_q,
                        investigation_question=q_planner,
                        result=tr,
                    )
                    turns = list(st.session_state.get("session_turns") or [])
                    row = serialize_turn(turn)
                    cand_map = st.session_state.get("er_candidates") or {}
                    if cand_map:
                        picks_raw = st.session_state.get("er_selections") or {}
                        extras = collect_er_candidate_node_ids(cand_map)
                        prios = collect_er_priority_node_ids(cand_map, picks_raw)
                        row["active_referents"] = extend_referents_with_node_ids(
                            row.get("active_referents") or {},
                            additional_ids=extras,
                            priority_ids=prios,
                        )
                        try:
                            row["active_referents"] = canonicalize_referents_dict(
                                row["active_referents"], get_graph()
                            )
                        except RuntimeError:
                            pass
                        st.session_state["er_candidates"] = {}
                        st.session_state["er_selections"] = {}
                    turns.append(row)
                    st.session_state["session_turns"] = turns[-30:]
                    st.session_state["session_active_referents"] = merge_session_referents(
                        st.session_state.get("session_active_referents"),
                        row.get("active_referents") or {},
                    )
                    st.rerun()
                except Exception as exc:
                    st.error("Run failed — see details below.")
                    st.exception(exc)

    compare_run = st.session_state.get("last_compare_run")
    last = st.session_state.get("last_tool_run")
    if compare_run:
        st.divider()
        st.caption("_Session memory and HTML export only include single-backend runs, not this comparison._")
        runs = compare_run.get("runs") or []
        if runs:
            summary = " · ".join(
                f"**{r.get('label', r.get('id', 'Backend'))}** {float(r.get('elapsed') or 0):.1f}s"
                for r in runs
            )
            st.markdown(f"**Comparison run** — {summary}")
            _render_compare_runs(runs)
        else:
            st.info("Comparison run completed but produced no results.")
    elif last is not None:
        _render_tool_planner_result(last)
    elif not (question or "").strip():
        st.caption("Enter a question above, then run an investigation to see results here.")


if __name__ == "__main__":
    main()
