"""
Evals — InvestigAI PoC v1

Browse the eval test set, filter to a bucket / template / claim, pick a sample
size, and run the LLM tool-planner agent against the selected questions.
Each run is graded against the ground-truth answer in ``eval/generated_qa.csv``.

Run the parent app from project root:
    PYTHONPATH=. streamlit run src/app/app.py
"""

from __future__ import annotations

import random
import sys
import time
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.project_env import load_project_dotenv  # noqa: E402
    load_project_dotenv()
except Exception:
    pass

from src.app.eval_runner import (  # noqa: E402
    EvalRow,
    all_buckets,
    load_eval_rows,
    score_answer,
    score_answer_llm,
)
from src.graph_query.native_read_mode import (  # noqa: E402
    force_networkx_reads,
    temporary_neo4j_read_llm_cypher,
    temporary_neo4j_read_native,
)
from src.graph_query.query_graph import get_graph, load_graph  # noqa: E402
from src.llm.tool_agent import run_tool_planner_agent  # noqa: E402


_BACKEND_LABEL_TO_ID: dict[str, str] = {
    "NetworkX (Dynamic Python)": "networkx",
    "Neo4j (NetworkX functions translated to Cypher)": "neo4j_native",
    "Neo4j (LLM writes Cypher directly)": "llm_cypher",
}
_SINGLE_BACKEND_LABELS: list[str] = list(_BACKEND_LABEL_TO_ID.keys())


def _backend_context(backend_id: str) -> AbstractContextManager[Any]:
    if backend_id == "networkx":
        return force_networkx_reads()
    if backend_id == "neo4j_native":
        return temporary_neo4j_read_native()
    if backend_id == "llm_cypher":
        return temporary_neo4j_read_llm_cypher()
    return nullcontext()


def _ensure_graph_loaded() -> None:
    try:
        get_graph()
    except RuntimeError:
        load_graph()


st.set_page_config(page_title="Evals — InvestigAI", layout="wide", page_icon="✅")
st.title("✅ Evals")
st.markdown(
    "Run the LLM tool-planner against ground-truth questions from "
    "`eval/generated_qa.csv`. Pick one or more **buckets** (the 8 investigator-question domains), "
    "narrow further by **template** or **claim**, choose how many tests to run, and click **Run evals**. "
    "Each answer is graded with a best-effort substring/coverage check against the expected answer."
)

try:
    _ensure_graph_loaded()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

# ── Load eval rows (cached to avoid re-parsing the 4k-row CSV on every rerun) ──
@st.cache_data(show_spinner=False)
def _load_rows() -> list[EvalRow]:
    return load_eval_rows()


try:
    rows = _load_rows()
except FileNotFoundError as e:
    st.error(f"Could not load eval CSV: {e}")
    st.stop()

if not rows:
    st.warning("No eval rows found.")
    st.stop()

# ── Sidebar / filters ─────────────────────────────────────────────────────────
st.subheader("1. Choose what to test")

# Buckets present in the data (skip empty ones).
present_bucket_idxs = sorted({r.bucket_idx for r in rows})
bucket_options = [(idx, title) for idx, title in all_buckets() if idx in present_bucket_idxs]
bucket_label_to_idx = {f"{idx}. {title}": idx for idx, title in bucket_options}

selected_bucket_labels = st.multiselect(
    "Buckets",
    options=list(bucket_label_to_idx.keys()),
    default=list(bucket_label_to_idx.keys()),
    help="The 8 investigator-question domains. Pick one (e.g., billing) or several.",
)
selected_bucket_idxs = {bucket_label_to_idx[b] for b in selected_bucket_labels}

# Filter rows by bucket first so downstream selectors only show relevant options.
bucket_rows = [r for r in rows if r.bucket_idx in selected_bucket_idxs]

c1, c2 = st.columns(2)
with c1:
    available_qids = sorted(
        {r.qid for r in bucket_rows},
        key=lambda q: int(q[1:]) if q[1:].isdigit() else 9999,
    )
    qid_label = {
        q: f"{q} — {next((r.question_template for r in bucket_rows if r.qid == q), '')[:80]}"
        for q in available_qids
    }
    selected_qids = st.multiselect(
        "Templates (qid)",
        options=available_qids,
        default=available_qids,
        format_func=lambda q: qid_label.get(q, q),
        help="Each qid is one templated question — e.g. Q28 = hourly rates per ICP.",
    )
with c2:
    available_claims = sorted({r.claim_number for r in bucket_rows if r.claim_number})
    selected_claims = st.multiselect(
        "Claims (optional)",
        options=available_claims,
        default=[],
        help="Leave empty to include all claims in the chosen buckets / templates.",
    )

# Final filtered pool.
def _matches(r: EvalRow) -> bool:
    if r.bucket_idx not in selected_bucket_idxs:
        return False
    if selected_qids and r.qid not in selected_qids:
        return False
    if selected_claims and r.claim_number not in selected_claims:
        return False
    return True


pool = [r for r in rows if _matches(r)]
st.caption(f"**{len(pool):,}** rows match the filters above (out of {len(rows):,} total).")

st.subheader("2. Sample size & strategy")

# Per-template sampling: total tests = tests_per_template × number of templates with data.
qids_in_pool = sorted(
    {r.qid for r in pool},
    key=lambda q: int(q[1:]) if q[1:].isdigit() else 9999,
)
max_per_template = max((sum(1 for r in pool if r.qid == q) for q in qids_in_pool), default=0)

c3, c4, c5 = st.columns([2, 2, 1])
with c3:
    tests_per_template = st.number_input(
        "Tests per template",
        min_value=1,
        max_value=max(1, max_per_template),
        value=1,
        step=1,
        help=(
            "Equal coverage: this many tests are sampled from each selected template. "
            "Total tests = (tests per template) × (templates with matching rows). "
            "A template with fewer matching rows than this number contributes all its rows."
        ),
    )
with c4:
    strategy = st.selectbox(
        "Sampling strategy",
        options=["Random", "First N"],
        index=0,
        help=(
            "Random: uniform sample within each template. "
            "First N: deterministic — take the first N rows of each template in CSV order."
        ),
    )
with c5:
    seed = st.number_input("Seed", value=42, step=1, help="For reproducible random sampling.")

run_mode = st.radio(
    "Single model or multiple model comparison",
    options=["Single model", "Multiple model comparison"],
    index=0,
    horizontal=True,
    help=(
        "**Single model** runs each selected eval on one graph backend. "
        "**Multiple model comparison** runs each eval against 2+ backends."
    ),
)
if run_mode == "Multiple model comparison":
    compare_labels = st.pills(
        "Models to compare (click to toggle)",
        options=_SINGLE_BACKEND_LABELS,
        selection_mode="multi",
        default=_SINGLE_BACKEND_LABELS,
        help=(
            "Click each model to include / exclude it. "
            "Total runs = (eval rows sampled) × (backends selected)."
        ),
    ) or []
    selected_backends = [(_BACKEND_LABEL_TO_ID[l], l) for l in compare_labels]
    if not selected_backends:
        st.warning("Select at least one backend to compare.")
else:
    single_label = st.pills(
        "Model",
        options=_SINGLE_BACKEND_LABELS,
        selection_mode="single",
        default=_SINGLE_BACKEND_LABELS[0],
        help=(
            "- **NetworkX (Dynamic Python)** — in-memory Python on a NetworkX DiGraph (default, no DB).\n"
            "- **Neo4j (NetworkX functions translated to Cypher)** — engineer-written Cypher of the same tools, running on Aura.\n"
            "- **Neo4j (LLM writes Cypher directly)** — model authors read-only Cypher per tool at runtime, executed on Aura."
        ),
    ) or _SINGLE_BACKEND_LABELS[0]
    selected_backends = [(_BACKEND_LABEL_TO_ID[single_label], single_label)]

use_llm_judge = st.checkbox(
    "Use LLM judge for scoring",
    value=True,
    help=(
        "On: an LLM (your configured backend) reads each (question, expected, actual) and decides pass/fail "
        "with a short rationale. Handles paraphrased 'unknown' answers, list-coverage, etc. "
        "Off: fast heuristic substring/regex grading. "
        "Override the judge model with EVAL_JUDGE_MODEL in .env (e.g., claude-haiku-4-5)."
    ),
)

# Project the actual total so the user sees the cost up front.
projected_total = sum(
    min(int(tests_per_template), sum(1 for r in pool if r.qid == q)) for q in qids_in_pool
)
projected_runs = projected_total * len(selected_backends)
st.caption(
    f"**Projected: {projected_runs} total run(s)** — "
    f"{projected_total} eval(s) × {len(selected_backends)} backend(s)."
)

if projected_runs > 25:
    st.warning(
        f"⚠️ You're about to run **{projected_runs}** LLM investigations. This will take "
        "minutes and incur API cost. Consider starting smaller to sanity-check."
    )


def _select_sample(
    pool: list[EvalRow], qids: list[str], per_template: int, strategy: str, seed: int
) -> list[EvalRow]:
    if not pool or per_template <= 0 or not qids:
        return []
    by_qid: dict[str, list[EvalRow]] = {}
    for r in pool:
        by_qid.setdefault(r.qid, []).append(r)
    rng = random.Random(seed)
    out: list[EvalRow] = []
    # Iterate qids in numeric order so output is stable when strategy = "First N".
    for q in sorted(qids, key=lambda x: int(x[1:]) if x[1:].isdigit() else 9999):
        rows_q = by_qid.get(q, [])
        if not rows_q:
            continue
        if strategy == "First N":
            out.extend(rows_q[:per_template])
        else:  # Random
            shuffled = rows_q[:]
            rng.shuffle(shuffled)
            out.extend(shuffled[:per_template])
    return out


st.subheader("3. Run")
run_btn = st.button("Run evals", type="primary", key="run_evals_btn", disabled=not pool)

if run_btn:
    sample = _select_sample(pool, qids_in_pool, int(tests_per_template), strategy, int(seed))
    total_runs = len(sample) * len(selected_backends)
    progress = st.progress(0.0, text=f"Running 0 / {total_runs}…")
    status = st.empty()
    results: list[dict] = []
    overall_start = time.time()
    completed_runs = 0

    for i, r in enumerate(sample, start=1):
        for backend_id, backend_label in selected_backends:
            status.markdown(
                f"**Test {i}/{len(sample)}** — `{r.qid}` on `{r.claim_number}` via **{backend_label}**  \n"
                f"_{r.question_text[:140]}{'…' if len(r.question_text) > 140 else ''}_"
            )
            t0 = time.time()
            actual_text = ""
            error_msg = ""
            try:
                with _backend_context(backend_id):
                    tr = run_tool_planner_agent(r.question_text)
                actual_text = (tr.final_text or "").strip()
                if tr.error and not actual_text:
                    error_msg = tr.error
            except Exception as exc:  # noqa: BLE001
                error_msg = f"{type(exc).__name__}: {exc}"
            elapsed = time.time() - t0

            if use_llm_judge:
                sr = score_answer_llm(
                    r.question_text, r.expected_answer_type, r.expected_answer, actual_text
                )
            else:
                sr = score_answer(r.expected_answer, r.expected_answer_type, actual_text)
            results.append(
                {
                    "qid": r.qid,
                    "bucket": f"{r.bucket_idx}. {r.bucket_title}",
                    "claim": r.claim_number,
                    "backend": backend_label,
                    "backend_id": backend_id,
                    "question": r.question_text,
                    "expected_type": r.expected_answer_type,
                    "expected": r.expected_answer,
                    "actual": actual_text,
                    "passed": sr.passed,
                    "score": sr.score,
                    "detail": sr.detail,
                    "elapsed_s": round(elapsed, 1),
                    "error": error_msg,
                }
            )
            completed_runs += 1
            progress.progress(
                completed_runs / max(total_runs, 1),
                text=f"Running {completed_runs} / {total_runs}…",
            )

    overall_elapsed = time.time() - overall_start
    progress.empty()
    status.empty()
    st.session_state["eval_results"] = results
    st.session_state["eval_elapsed_s"] = overall_elapsed

# ── Results ───────────────────────────────────────────────────────────────────
results = st.session_state.get("eval_results")
if results:
    st.divider()
    st.subheader("Results")

    df = pd.DataFrame(results)
    if "backend" not in df.columns:
        df["backend"] = "NetworkX (Dynamic Python)"
    n = len(df)
    n_pass = int(df["passed"].sum())
    n_fail = n - n_pass
    overall_elapsed = st.session_state.get("eval_elapsed_s", 0.0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Runs", n)
    m2.metric("Passed", n_pass)
    m3.metric("Failed", n_fail)
    m4.metric("Total time", f"{overall_elapsed:.0f}s")

    if "backend" in df.columns and df["backend"].nunique() > 1:
        st.markdown("**Pass rate by backend**")
        backend_agg = (
            df.groupby("backend")
            .agg(runs=("passed", "size"), passed=("passed", "sum"), avg_time_s=("elapsed_s", "mean"))
            .reset_index()
        )
        backend_agg["pass_rate"] = (backend_agg["passed"] / backend_agg["runs"]).map(lambda v: f"{v*100:.0f}%")
        st.dataframe(
            backend_agg,
            hide_index=True,
            width=1200,
            column_config={"avg_time_s": st.column_config.NumberColumn("avg time (s)", format="%.1f")},
        )

    # Per-bucket pass rate.
    if "bucket" in df.columns and df["bucket"].notna().any():
        st.markdown("**Pass rate by bucket**")
        agg = (
            df.groupby("bucket")
            .agg(tests=("passed", "size"), passed=("passed", "sum"))
            .reset_index()
        )
        agg["pass_rate"] = (agg["passed"] / agg["tests"]).map(lambda v: f"{v*100:.0f}%")
        st.dataframe(agg, hide_index=True, width=1200)

    st.markdown("**Per-test results**")
    table_df = df[
        [
            "qid",
            "bucket",
            "claim",
            "backend",
            "passed",
            "score",
            "elapsed_s",
            "expected_type",
            "expected",
            "actual",
            "detail",
        ]
    ].copy()
    table_df["actual"] = table_df["actual"].str.slice(0, 240)
    table_df["expected"] = table_df["expected"].str.slice(0, 240)
    st.dataframe(
        table_df,
        hide_index=True,
        width=1200,
        column_config={
            "passed": st.column_config.CheckboxColumn("pass"),
            "score": st.column_config.NumberColumn("score", format="%.2f"),
            "elapsed_s": st.column_config.NumberColumn("time (s)", format="%.1f"),
        },
    )

    st.markdown("**Inspect a single test**")
    options = list(range(len(results)))
    pick = st.selectbox(
        "Select a test to expand",
        options=options,
        format_func=lambda i: (
            f"{results[i]['qid']} · {results[i]['claim']} · "
            f"{results[i].get('backend', 'NetworkX (Dynamic Python)')} · "
            f"{'PASS' if results[i]['passed'] else 'FAIL'}"
        ),
    )
    if pick is not None:
        r = results[pick]
        st.markdown(f"**Question:** {r['question']}")
        st.markdown(f"**Bucket:** {r['bucket']}")
        st.markdown(f"**Backend:** {r.get('backend', 'NetworkX (Dynamic Python)')}")
        st.markdown(f"**Expected ({r['expected_type']}):**")
        st.code(r["expected"] or "(empty)", language="json" if r["expected_type"] in ("list", "object") else None)
        st.markdown("**Actual answer:**")
        st.markdown(r["actual"] or "_(no answer)_")
        st.markdown(f"**Grader:** {'✅ pass' if r['passed'] else '❌ fail'} — {r['detail']} (score {r['score']:.2f})")
        if r.get("error"):
            st.error(r["error"])

    st.download_button(
        "Download results as CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="eval_results.csv",
        mime="text/csv",
    )
else:
    st.caption("No results yet. Configure the filters above and click **Run evals**.")
