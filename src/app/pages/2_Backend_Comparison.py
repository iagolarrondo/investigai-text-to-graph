"""
Backend comparisons — named probes and full **NL investigations** side by side.

Multipage app: run from repo root::

    PYTHONPATH=. streamlit run src/app/app.py

Use the **sidebar Run buttons** so actions stay visible while you scroll inputs.
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import pandas as pd
import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.project_env import load_project_dotenv

    load_project_dotenv()
except ImportError:
    pass

from src.graph_query.backend_compare import ComparisonBatchResult, QUERY_RUNNERS, run_comparison_batch
from src.graph_query.nl_backend_compare import NlDualCompareResult, run_nl_dual_hydrate, run_nl_dual_nx_vs_cypher
from src.graph_query.nx_native_compare import (
    NX_NATIVE_QUERY_RUNNERS,
    NxNativeComparisonBatchResult,
    run_nx_vs_native_batch,
)

_BC_KEY = "bc_graph_pair_cache"
_BC_NX_KEY = "bc_nx_native_graph_cache"
_BC_LAST = "_bc_last_comparison_payload"
_BC_NL_LAST = "_bc_last_nl_comparison"


def _mode_slug(m: str) -> str:
    return "hydrate" if m.startswith("Hydrate") else "nx_native"


def _pretty_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)


def _render_query_outputs(batch: ComparisonBatchResult | NxNativeComparisonBatchResult, variant: str) -> None:
    st.subheader("Query outputs — side by side")
    names = [p.name for p in batch.probes]
    pick = st.selectbox("Choose query / probe to inspect", names, key=f"bc_output_pick_{variant}")
    row = next(p for p in batch.probes if p.name == pick)
    if isinstance(batch, ComparisonBatchResult):
        left_lbl, right_lbl = "CSV → NetworkX", "Neo4j → NetworkX"
        left_obj, right_obj = row.norm_csv, row.norm_neo
    else:
        left_lbl, right_lbl = "NetworkX scan", "Neo4j Cypher"
        left_obj, right_obj = row.norm_nx, row.norm_native
    if left_obj is None or right_obj is None:
        st.warning("Normalized payloads missing — run a probe comparison again.")
        return
    o1, o2 = st.columns(2)
    with o1:
        st.caption(left_lbl)
        st.json(left_obj)
    with o2:
        st.caption(right_lbl)
        st.json(right_obj)
    with st.expander("Same data as raw JSON (copy-friendly)"):
        cj1, cj2 = st.columns(2)
        with cj1:
            st.code(_pretty_json(left_obj), language="json")
        with cj2:
            st.code(_pretty_json(right_obj), language="json")


def _render_nl_outputs(res: NlDualCompareResult) -> None:
    st.subheader("NL investigation — side by side")
    m1, m2, m3 = st.columns(3)
    m1.metric(f"{res.left_label} (s)", f"{res.left_ms / 1000:.1f}")
    m2.metric(f"{res.right_label} (s)", f"{res.right_ms / 1000:.1f}")
    m3.metric("Normalized trace match", "yes" if res.normalized_match else "no")
    if not res.normalized_match and res.mismatch_detail:
        with st.expander("Normalized diff (traces may differ while answers align)"):
            st.code(res.mismatch_detail)
    st.caption(
        "Two separate LLM runs — tool order and wording can differ. Compare **final answers** and tool payloads below."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"### {res.left_label}")
        if res.left.error:
            st.error(res.left.error)
        st.markdown(res.left.final_text or "_(empty)_")
    with c2:
        st.markdown(f"### {res.right_label}")
        if res.right.error:
            st.error(res.right.error)
        st.markdown(res.right.final_text or "_(empty)_")
    with st.expander("Tool steps — left"):
        st.json(
            [
                {"tool": s.tool, "input": s.input, "phase": s.planner_phase, "preview": s.result_preview[:2000]}
                for s in res.left.steps
            ]
        )
    with st.expander("Tool steps — right"):
        st.json(
            [
                {"tool": s.tool, "input": s.input, "phase": s.planner_phase, "preview": s.result_preview[:2000]}
                for s in res.right.steps
            ]
        )


st.set_page_config(page_title="Backend comparison — InvestigAI", layout="wide", page_icon="⚖️")
st.title("⚖️ Backend comparison")
st.caption(
    "Named probes: deterministic ``query_graph`` calls. NL: full planner → judge → synthesis **twice** "
    "(costs two investigations). **Use the sidebar** to run — buttons stay visible when you scroll."
)

screen = st.radio(
    "What to compare",
    ("Named probes (deterministic)", "NL investigation (LLM × 2)"),
    horizontal=True,
    key="bc_screen",
)

compare_mode = st.radio(
    "Comparison mode",
    ("Hydrate: CSV vs Neo4j → NetworkX", "Execution: NetworkX scan vs Neo4j Cypher"),
    horizontal=True,
    help="Applies to **Named probes** and **NL investigation**.",
    key="bc_compare_mode",
)

if compare_mode.startswith("Hydrate"):
    st.markdown(
        "**Hydrate:** same logic on **CSV → NetworkX** vs **Neo4j → NetworkX** (both scan in-memory graphs)."
    )
else:
    st.markdown(
        "**NX vs Cypher:** one CSV graph — left scans NetworkX; right uses **native Cypher** on Aura for ported tools."
    )

nl_question = ""
nl_max_rounds = 0

# --- Named probe inputs ---
if screen.startswith("Named"):
    if compare_mode.startswith("Hydrate"):
        probe_names = sorted(QUERY_RUNNERS)
    else:
        probe_names = sorted(NX_NATIVE_QUERY_RUNNERS)
    default_probes = ["summarize", "catalog"]
    selected = st.multiselect("Queries to run (probes)", probe_names, default=default_probes, key="bc_probes")

    c1, c2, c3 = st.columns(3)
    with c1:
        claim_id = st.text_input(
            "Claim id",
            value="",
            help="claim_network / claim_subgraph",
            placeholder="claim_C9000000001",
            key="bc_claim",
        )
    with c2:
        search_q = st.text_input(
            "Search substring",
            value="",
            help="search_nodes",
            placeholder="WILSON",
            key="bc_search",
        )
    with c3:
        max_depth = st.number_input(
            "Subgraph max_depth (claim / person)", min_value=1, max_value=10, value=2, key="bc_depth"
        )

    person_id = st.text_input(
        "Person id",
        value="",
        help="person_subgraph, person_policies, policies_coparties",
        placeholder="person_P123",
        key="bc_person",
    )
    policy_id = st.text_input(
        "Policy id",
        value="",
        help="policy_network",
        placeholder="policy_POL001",
        key="bc_policy",
    )
    neighbor_node_id = st.text_input(
        "Neighbor anchor node id",
        value="",
        help="neighbors probe",
        placeholder="person_P123",
        key="bc_neighbor",
    )

    node_type = st.text_input("Optional search_nodes node_type", value="", key="bc_ntype")
    search_limit = st.number_input("search_nodes limit", min_value=1, max_value=200, value=40, key="bc_slimit")

    ns = Namespace(
        claim_id=claim_id,
        max_depth=int(max_depth),
        search_q=search_q,
        node_type=node_type,
        search_limit=int(search_limit),
        person_id=person_id,
        policy_id=policy_id,
        neighbor_node_id=neighbor_node_id,
    )
else:
    nl_question = st.text_area(
        "Investigation question",
        height=120,
        placeholder="e.g. Summarize the graph and any shared bank accounts between people.",
        key="bc_nl_q",
    )
    nl_max_rounds = st.number_input(
        "Optional cap: planner max rounds per phase (0 = use env default)",
        min_value=0,
        max_value=40,
        value=0,
        key="bc_nl_rounds",
        help="Lower for faster/smaller runs on this screen.",
    )
    selected = []
    ns = Namespace()

cache_col, timing_col = st.columns(2)
with cache_col:
    keep_cache = st.checkbox(
        "Reuse cached graph(s) for the next run",
        value=False,
        key="bc_keep_cache",
    )
with timing_col:
    show_probe_timing = st.checkbox("Show per-probe timings (ms)", value=True, key="bc_timing")

# --- Sidebar: always-visible run actions ---
with st.sidebar:
    st.header("Run")
    st.markdown("Run the comparison for the **screen** and **mode** selected above.")
    run_probes = st.button("▶ Run probe comparison", type="primary", key="sb_run_probes")
    run_nl = st.button("▶ Run NL investigation compare", type="primary", key="sb_run_nl")
    st.divider()
    if st.button("Clear caches", key="sb_clear"):
        st.session_state.pop(_BC_KEY, None)
        st.session_state.pop(_BC_NX_KEY, None)
        st.session_state.pop(_BC_LAST, None)
        st.session_state.pop(_BC_NL_LAST, None)
        st.rerun()

# Duplicate main-area buttons (some users never open the sidebar)
btn_col1, btn_col2 = st.columns(2)
with btn_col1:
    main_run_probes = st.button("▶ Run probe comparison", type="primary", key="main_run_probes")
with btn_col2:
    main_run_nl = st.button("▶ Run NL investigation compare", type="primary", key="main_run_nl")

do_probes = screen.startswith("Named") and (run_probes or main_run_probes)
do_nl = screen.startswith("NL") and (run_nl or main_run_nl)

if do_probes:
    if not selected:
        st.warning("Pick at least one probe.")
    elif compare_mode.startswith("Hydrate"):
        cached_pair = st.session_state.get(_BC_KEY) if keep_cache else None
        try:
            with st.spinner("Loading graphs and running probes …"):
                batch = run_comparison_batch(
                    selected,
                    ns,
                    cached_graphs=cached_pair,
                    store_normalized_payloads=True,
                )
        except ValueError as exc:
            st.error(str(exc))
        except FileNotFoundError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Load failed (Neo4j credentials, Aura, or network): {exc}")
        else:
            if keep_cache:
                st.session_state[_BC_KEY] = batch.graphs
            else:
                st.session_state.pop(_BC_KEY, None)

            if batch.hydrate_csv_ms is not None and batch.hydrate_neo_ms is not None:
                m1, m2, m3 = st.columns(3)
                m1.metric("Hydrate CSV (ms)", f"{batch.hydrate_csv_ms:,.0f}")
                m2.metric("Hydrate Neo4j (ms)", f"{batch.hydrate_neo_ms:,.0f}")
                ratio = (
                    batch.hydrate_neo_ms / batch.hydrate_csv_ms
                    if batch.hydrate_csv_ms > 0
                    else float("nan")
                )
                m3.metric("Neo4j / CSV (hydrate)", f"{ratio:.2f}×")
            else:
                st.info("Using **cached** graphs — hydrate timings omitted.")

            st.caption(
                f"Shape — CSV: **{batch.nodes_csv}** nodes · **{batch.edges_csv}** edges · "
                f"Neo4j: **{batch.nodes_neo}** nodes · **{batch.edges_neo}** edges"
            )

            table_rows = []
            all_ok = True
            for row in batch.probes:
                if not row.accurate:
                    all_ok = False
                r = {"probe": row.name, "accurate": row.accurate}
                if show_probe_timing:
                    r["query_csv_ms"] = round(row.query_csv_ms, 2)
                    r["query_neo_ms"] = round(row.query_neo_ms, 2)
                    r["delta_ms"] = round(row.query_neo_ms - row.query_csv_ms, 2)
                table_rows.append(r)
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

            if all_ok:
                st.success("All selected probes **MATCH** between CSV and Neo4j graphs.")
            else:
                st.error("At least one probe **mismatch** — expand sections below.")
                for row in batch.probes:
                    if row.accurate or not row.mismatch_detail:
                        continue
                    with st.expander(f"Diff: `{row.name}`"):
                        st.code(row.mismatch_detail)
            st.session_state[_BC_LAST] = (_mode_slug(compare_mode), batch)
            st.session_state.pop(_BC_NL_LAST, None)
    else:
        cached_g = st.session_state.get(_BC_NX_KEY) if keep_cache else None
        try:
            with st.spinner("Loading CSV graph and running NX vs Cypher …"):
                batch = run_nx_vs_native_batch(
                    selected,
                    ns,
                    cached_graph=cached_g,
                    store_normalized_payloads=True,
                )
        except ValueError as exc:
            st.error(str(exc))
        except FileNotFoundError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Cypher or Neo4j session failed: {exc}")
        else:
            if keep_cache:
                st.session_state[_BC_NX_KEY] = batch.graph
            else:
                st.session_state.pop(_BC_NX_KEY, None)

            if batch.hydrate_csv_ms is not None:
                st.metric("Load CSV graph (ms)", f"{batch.hydrate_csv_ms:,.0f}")
            else:
                st.info("Using **cached** CSV graph — load timing omitted.")

            st.caption(
                f"Shape — CSV (NX path): **{batch.nodes_csv}** nodes · **{batch.edges_csv}** edges"
            )

            table_rows = []
            all_ok = True
            for row in batch.probes:
                if not row.accurate:
                    all_ok = False
                r = {"probe": row.name, "accurate": row.accurate}
                if show_probe_timing:
                    r["nx_scan_ms"] = round(row.query_nx_ms, 2)
                    r["cypher_ms"] = round(row.query_native_ms, 2)
                    r["delta_ms"] = round(row.query_native_ms - row.query_nx_ms, 2)
                table_rows.append(r)
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

            if all_ok:
                st.success("All selected probes **MATCH** between NX scan and native Cypher.")
            else:
                st.error("At least one probe **mismatch** — expand sections below.")
                for row in batch.probes:
                    if row.accurate or not row.mismatch_detail:
                        continue
                    with st.expander(f"Diff: `{row.name}`"):
                        st.code(row.mismatch_detail)
            st.session_state[_BC_LAST] = (_mode_slug(compare_mode), batch)
            st.session_state.pop(_BC_NL_LAST, None)

if do_nl:
    q = (nl_question or "").strip()
    if not q:
        st.warning("Enter an investigation question.")
    else:
        mr = int(nl_max_rounds)
        max_r = mr if mr > 0 else None
        cached_pair = st.session_state.get(_BC_KEY) if keep_cache else None
        cached_g = st.session_state.get(_BC_NX_KEY) if keep_cache else None
        nl_res = None
        try:
            if compare_mode.startswith("Hydrate"):
                with st.spinner("NL compare: two full investigations (CSV vs Neo4j hydrate) …"):
                    nl_res, h1, h2 = run_nl_dual_hydrate(q, max_rounds=max_r, cached_graphs=cached_pair)
                if h1 is not None and h2 is not None:
                    a1, a2, a3 = st.columns(3)
                    a1.metric("Hydrate CSV (ms)", f"{h1:,.0f}")
                    a2.metric("Hydrate Neo4j (ms)", f"{h2:,.0f}")
                    a3.metric("Neo4j / CSV hydrate", f"{h2 / h1:.2f}×" if h1 > 0 else "—")
                if keep_cache and nl_res.cached_graph_pair is not None:
                    st.session_state[_BC_KEY] = nl_res.cached_graph_pair
            else:
                with st.spinner("NL compare: NX scan vs native Cypher (two full investigations) …"):
                    nl_res, hcsv = run_nl_dual_nx_vs_cypher(q, max_rounds=max_r, cached_graph=cached_g)
                if hcsv is not None:
                    st.metric("Load CSV graph (ms)", f"{hcsv:,.0f}")
                if keep_cache and nl_res.cached_graph_csv is not None:
                    st.session_state[_BC_NX_KEY] = nl_res.cached_graph_csv
        except ValueError as exc:
            st.error(str(exc))
        except FileNotFoundError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(str(exc))
        else:
            if nl_res is not None:
                st.session_state[_BC_NL_LAST] = (_mode_slug(compare_mode), nl_res)
                st.session_state.pop(_BC_LAST, None)

_last = st.session_state.get(_BC_LAST)
if _last is not None and screen.startswith("Named"):
    variant, batch_obj = _last
    if variant == _mode_slug(compare_mode):
        _render_query_outputs(batch_obj, variant)

_nl = st.session_state.get(_BC_NL_LAST)
if _nl is not None and screen.startswith("NL"):
    variant_nl, nl_obj = _nl
    if variant_nl == _mode_slug(compare_mode):
        _render_nl_outputs(nl_obj)
