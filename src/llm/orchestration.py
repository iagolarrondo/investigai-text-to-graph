"""
Investigation **orchestrator**: planner phases (tool loop) ↔ coverage judge
(uncapped outer loop), then **synthesis** for the user-visible answer and graph focus.

Backends: **Gemini** (``INVESTIGATION_LLM=gemini``), **Anthropic Claude** (``INVESTIGATION_LLM=anthropic``),
or **local Ollama** (``INVESTIGATION_LLM=ollama``).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

from src.graph_query.query_graph import get_graph
from src.llm.json_extract import extract_json_object
from src.llm.prompts import (
    SYSTEM_COVERAGE_JUDGE,
    SYSTEM_COVERAGE_JUDGE_OLLAMA,
    SYSTEM_INVESTIGATION_SYNTHESIS,
    SYSTEM_INVESTIGATION_SYNTHESIS_ANTHROPIC,
    SYSTEM_INVESTIGATION_SYNTHESIS_GEMINI,
    SYSTEM_INVESTIGATION_SYNTHESIS_OLLAMA,
    SYSTEM_TOOL_AGENT,
    load_graph_llm_summary_text,
)
from src.llm.tool_agent import (
    ANTHROPIC_MODEL,
    JudgeRoundInfo,
    MODEL,
    OLLAMA_MODEL,
    ToolAgentResult,
    ToolAgentStep,
    investigation_llm_backend,
    refresh_graph_tools_with_extensions,
    run_planner_phase,
)


_NODE_ID_RE = re.compile(r"\b(Person|Claim|Policy|Bank|Address|Business)\|[A-Za-z0-9_.-]+\b")


def _first_graph_node_id_from_steps(steps: list[ToolAgentStep]) -> str | None:
    """Pick a plausible summary-graph focus id from tool output text."""
    blob = "\n".join(s.result_preview for s in steps)
    m = _NODE_ID_RE.search(blob)
    return m.group(0) if m else None


def _ollama_max_trace_chars() -> int:
    raw = (os.environ.get("OLLAMA_MAX_TRACE_CHARS") or "").strip()
    if not raw:
        return 28_000
    try:
        n = int(raw)
        return max(6_000, n)
    except ValueError:
        return 28_000


def _truncate_for_local_llm(blob: str, max_chars: int) -> str:
    if len(blob) <= max_chars:
        return blob
    head = max_chars // 2
    tail = max_chars - head - 120
    return (
        blob[:head]
        + "\n\n[... middle of tool trace omitted for local model context ...]\n\n"
        + blob[-tail:]
    )


def _hosted_synthesis_system_with_graph_summary(base_system: str) -> str:
    """Append ``graph_llm_summary.md`` so hosted synthesis stays current without process restarts."""
    if "<graph_llm_summary>" in base_system:
        return base_system
    summary = load_graph_llm_summary_text()
    return base_system + "\n\n<graph_llm_summary>\n" + summary + "\n</graph_llm_summary>"


def _serialize_trace_for_judge(question: str, steps: list[ToolAgentStep]) -> str:
    parts: list[str] = [
        f"USER_QUESTION:\n{question}\n",
        "\n--- FULL_TOOL_TRACE (chronological; outputs are complete, not shortened) ---\n",
    ]
    for i, s in enumerate(steps, start=1):
        parts.append(
            f"\n### Step {i} (planner phase {s.planner_phase}): `{s.tool}`\n"
            f"INPUT:\n{json.dumps(s.input, indent=2, default=str)}\n"
            f"OUTPUT:\n{s.result_preview}\n"
        )
    return "".join(parts)


def _serialize_trace_for_synthesis(question: str, steps: list[ToolAgentStep]) -> str:
    return _serialize_trace_for_judge(question, steps)


def _normalize_focus_node_id(raw: object) -> str | None:
    if raw is None or raw in ("", "null"):
        return None
    s = str(raw).strip()
    if not s or s.lower() == "null":
        return None
    try:
        G = get_graph()
    except RuntimeError:
        return s if "|" in s else None
    if s in G:
        return s
    return None


def _gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _max_planner_phases() -> int | None:
    raw = (os.environ.get("INVESTIGATION_MAX_PLANNER_PHASES") or "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    return n if n > 0 else None


def _max_total_tool_steps() -> int | None:
    """Hard cap on recorded tool steps per investigation (across planner phases). ``None`` = unlimited."""
    raw = (os.environ.get("INVESTIGATION_MAX_TOOL_STEPS") or "").strip()
    if not raw:
        return 20
    try:
        n = int(raw)
    except ValueError:
        return 20
    if n <= 0:
        return None
    return min(n, 500)


def _planner_max_rounds(backend: str, override: int | None) -> int:
    """Tool-call rounds per planner segment (one LLM request may include multiple tool calls)."""
    if override is not None:
        return max(1, min(override, 64))
    raw = (os.environ.get("INVESTIGATION_PLANNER_MAX_ROUNDS") or "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return min(n, 64)
        except ValueError:
            pass
    # Defaults favor shorter runs; raise with INVESTIGATION_PLANNER_MAX_ROUNDS when you need depth.
    if backend == "ollama":
        return 12
    return 14


def _ollama_client_timeout() -> float | None:
    raw = (os.environ.get("OLLAMA_TIMEOUT") or "").strip()
    if not raw:
        return 600.0
    try:
        sec = float(raw)
    except ValueError:
        return 600.0
    if sec <= 0:
        return None
    return sec


def _planner_append_user(backend: str, state: list[Any], text: str) -> None:
    if backend in ("ollama", "anthropic"):
        state.append({"role": "user", "content": text})
        return
    from google.genai import types

    state.append(types.Content(role="user", parts=[types.Part(text=text)]))


def _inject_planner_preflight_seed(backend: str, planner_state: list[Any], seed: str) -> None:
    """Append optional preflight hints to the first user turn (same conversation the planner sees)."""
    s = (seed or "").strip()
    if not s or not planner_state:
        return
    block = "\n\n--- Preflight planner seed ---\n" + s
    if backend in ("ollama", "anthropic"):
        for row in planner_state:
            if isinstance(row, dict) and row.get("role") == "user":
                row["content"] = str(row.get("content", "")) + block
                return
        return
    try:
        c0 = planner_state[0]
        parts = getattr(c0, "parts", None)
        if parts:
            t0 = getattr(parts[0], "text", "") or ""
            parts[0].text = t0 + block
    except Exception:
        return


def run_investigation_orchestrator(
    question: str,
    *,
    planner_max_rounds_per_phase: int | None = None,
    progress_cb: callable | None = None,
) -> ToolAgentResult:
    """
    Outer loop: planner phase → judge → if not satisfied, feedback and repeat; then synthesis.

    ``INVESTIGATION_LLM``: ``gemini``, ``anthropic`` (``ANTHROPIC_API_KEY``), or ``ollama`` (local).

    Tuning: ``INVESTIGATION_PLANNER_MAX_ROUNDS``, ``INVESTIGATION_MAX_PLANNER_PHASES``,
    and for Ollama ``OLLAMA_TIMEOUT`` (seconds; ``0`` = no limit).
    """
    out = ToolAgentResult(question=question.strip())

    def _emit(event_type: str, message: str, **data: Any) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb({"type": event_type, "message": message, **data})
        except Exception:
            return

    backend = investigation_llm_backend()
    effective_max_rounds = _planner_max_rounds(backend, planner_max_rounds_per_phase)
    # When INVESTIGATION_MAX_PLANNER_PHASES forces synthesis, prepend context so the model
    # hedges and surfaces follow-ups instead of sounding "done".
    synth_user_prefix_holder: list[str] = [""]

    if backend == "ollama":
        try:
            from ollama import Client
        except ImportError:
            out.error = "Install Ollama support: pip install ollama. Also install Ollama from https://ollama.com"
            return out
        from src.llm.local_ollama import ollama_generate_text

        host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
        client: Any = Client(host=host, timeout=_ollama_client_timeout())
        model_name = OLLAMA_MODEL
        planner_state: list[Any] = [
            {"role": "system", "content": SYSTEM_TOOL_AGENT},
            {"role": "user", "content": out.question},
        ]
        _trace_lim = _ollama_max_trace_chars()

        def _judge_raw() -> str:
            blob = _serialize_trace_for_judge(out.question, out.steps)
            return ollama_generate_text(
                client,
                model=model_name,
                system_instruction=SYSTEM_COVERAGE_JUDGE_OLLAMA,
                user_text=_truncate_for_local_llm(blob, _trace_lim),
                num_predict=4096,
                json_mode=True,
            )

        def _synth_raw() -> str:
            blob = _serialize_trace_for_synthesis(out.question, out.steps)
            intro = "Produce the JSON described in your instructions.\n\n"
            pre = synth_user_prefix_holder[0].strip()
            if pre:
                intro = pre + "\n\n" + intro
            return ollama_generate_text(
                client,
                model=model_name,
                system_instruction=SYSTEM_INVESTIGATION_SYNTHESIS_OLLAMA,
                user_text=intro + _truncate_for_local_llm(blob, _trace_lim),
                num_predict=8192,
                json_mode=True,
            )

    elif backend == "anthropic":
        try:
            from anthropic import Anthropic
        except ImportError:
            out.error = "Install Anthropic support: pip install anthropic"
            return out
        from src.llm.anthropic_llm import anthropic_generate_text

        api_key_a = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key_a:
            out.error = "ANTHROPIC_API_KEY is not set."
            return out
        client = Anthropic(api_key=api_key_a)
        model_name = ANTHROPIC_MODEL
        planner_state: list[Any] = [{"role": "user", "content": out.question}]

        def _judge_raw() -> str:
            return anthropic_generate_text(
                client,
                model=model_name,
                system_instruction=SYSTEM_COVERAGE_JUDGE,
                user_text=_serialize_trace_for_judge(out.question, out.steps),
                max_tokens=4096,
            )

        def _synth_raw() -> str:
            blob = _serialize_trace_for_synthesis(out.question, out.steps)
            intro = "Produce the JSON described in your instructions.\n\n"
            pre = synth_user_prefix_holder[0].strip()
            if pre:
                intro = pre + "\n\n" + intro
            full_domain = (os.environ.get("INVESTIGATION_ANTHROPIC_SYNTHESIS_FULL_DOMAIN_DOCS") or "").strip().lower()
            synth_system = (
                SYSTEM_INVESTIGATION_SYNTHESIS
                if full_domain in ("1", "true", "yes", "on")
                else _hosted_synthesis_system_with_graph_summary(SYSTEM_INVESTIGATION_SYNTHESIS_ANTHROPIC)
            )
            return anthropic_generate_text(
                client,
                model=model_name,
                system_instruction=synth_system,
                user_text=intro + blob,
                max_tokens=8192,
            )

    else:
        from google import genai
        from google.genai import types

        from src.llm.gemini_llm import generate_text

        api_key = _gemini_api_key()
        if not api_key:
            out.error = "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set."
            return out
        client = genai.Client(api_key=api_key)
        model_name = MODEL
        planner_state = [
            types.Content(role="user", parts=[types.Part(text=out.question)]),
        ]

        def _judge_raw() -> str:
            return generate_text(
                client,
                model=model_name,
                system_instruction=SYSTEM_COVERAGE_JUDGE,
                user_text=_serialize_trace_for_judge(out.question, out.steps),
                max_output_tokens=4096,
            )

        def _synth_raw() -> str:
            blob = _serialize_trace_for_synthesis(out.question, out.steps)
            intro = "Produce the JSON described in your instructions.\n\n"
            pre = synth_user_prefix_holder[0].strip()
            if pre:
                intro = pre + "\n\n" + intro
            full_domain = (os.environ.get("INVESTIGATION_GEMINI_SYNTHESIS_FULL_DOMAIN_DOCS") or "").strip().lower()
            synth_system = (
                SYSTEM_INVESTIGATION_SYNTHESIS
                if full_domain in ("1", "true", "yes", "on")
                else _hosted_synthesis_system_with_graph_summary(SYSTEM_INVESTIGATION_SYNTHESIS_GEMINI)
            )
            return generate_text(
                client,
                model=model_name,
                system_instruction=synth_system,
                user_text=intro + blob,
                max_output_tokens=8192,
            )

    from src.llm.extension_author import try_author_extension
    from src.llm.tool_preflight import run_tool_preflight, tool_catalog_json_from_graph_tools

    refresh_graph_tools_with_extensions()
    try:
        _emit("tool_eval_start", "Tool evaluation: checking whether existing tools cover your question…")
        out.preflight = run_tool_preflight(backend, client, model_name, out.question)
        _emit(
            "tool_eval_done",
            f"Tool evaluation complete: decision={str((out.preflight or {}).get('decision', 'sufficient'))}",
            decision=str((out.preflight or {}).get("decision", "")),
        )
    except Exception as exc:
        out.preflight = {
            "decision": "sufficient",
            "rationale": f"Preflight raised {type(exc).__name__}; continuing without extension.",
            "gap_summary": "",
            "efficiency_note": "",
            "recommended_plan": "",
            "preflight_error": str(exc),
        }

    decision = str((out.preflight or {}).get("decision", "sufficient")).strip().lower()
    if decision in ("insufficient", "sufficient_but_inefficient"):
        _emit("extension_author_start", "Extension authoring: generating a new helper tool…")
        out.extension_authoring = try_author_extension(
            backend=backend,
            client=client,
            model_name=model_name,
            question=out.question,
            preflight=out.preflight or {},
            tool_catalog_json=tool_catalog_json_from_graph_tools(),
        )
        _emit(
            "extension_author_done",
            "Extension authoring complete.",
            activated=bool((out.extension_authoring or {}).get("activated")),
            tool_name=str((out.extension_authoring or {}).get("tool_name", "")),
        )
        if (out.extension_authoring or {}).get("activated"):
            refresh_graph_tools_with_extensions()
    else:
        out.extension_authoring = None

    plan = str((out.preflight or {}).get("recommended_plan", "")).strip()
    eff = str((out.preflight or {}).get("efficiency_note", "")).strip()
    if plan or eff:
        bits = []
        if plan:
            bits.append(f"Suggested plan: {plan}")
        if eff:
            bits.append(f"Efficiency note: {eff}")
        _inject_planner_preflight_seed(backend, planner_state, "\n".join(bits))

    phase = 0
    planner_phases_run = 0
    no_tool_streak = 0
    bad_judge_streak = 0
    max_phases = _max_planner_phases()
    max_tool_steps = _max_total_tool_steps()
    force_synth_after_judge = False

    while True:
        phase_label = "Tool Steps" if phase == 0 else f"Planner phase {phase}"
        _emit("planner_phase_start", f"{phase_label}: choosing and running tools…", planner_phase=phase)
        before = len(out.steps)
        try:
            planner_state, n_calls = run_planner_phase(
                client,
                planner_state,
                out.steps,
                planner_phase=phase,
                max_rounds=effective_max_rounds,
                progress_cb=progress_cb,
                max_total_tool_steps=max_tool_steps,
            )
        except RuntimeError as exc:
            out.error = str(exc)
            return out
        out.raw_messages += n_calls
        _emit(
            "planner_phase_done",
            f"{phase_label} complete (tool steps so far: {len(out.steps)})",
            planner_phase=phase,
            step_count=len(out.steps),
        )
        if max_tool_steps is not None and len(out.steps) >= max_tool_steps:
            synth_user_prefix_holder[0] = (
                f"STOPPED_TOOLING: Recorded **{max_tool_steps}** tool step(s) maximum "
                "(`INVESTIGATION_MAX_TOOL_STEPS`, default **20**) — **no further tools** will run even if "
                "the reviewer asks for more.\n"
                "Reviewer: treat coverage as **best-effort** given the cap; if gaps remain, say so clearly in "
                "`missing_aspects` but still allow synthesis to proceed.\n"
                "Synthesis: summarize only tool-backed facts; state uncertainty and capped depth plainly."
            )
            force_synth_after_judge = True

        if len(out.steps) == before and n_calls >= effective_max_rounds:
            out.error = (
                "Planner hit max API rounds for this phase without finishing. "
                "Try a narrower question or raise planner_max_rounds_per_phase."
            )
            return out

        if len(out.steps) == before:
            no_tool_streak += 1
            if no_tool_streak > 3:
                out.error = "Planner repeatedly ended without calling tools."
                return out
            _planner_append_user(
                backend,
                planner_state,
                (
                    "You must invoke at least one graph investigation tool "
                    "(for example search_nodes, get_graph_relationship_catalog, summarize_graph, "
                    "get_claim_network, get_person_policies, …) before stopping this segment."
                ),
            )
            continue
        no_tool_streak = 0
        planner_phases_run += 1

        try:
            _emit("review_start", "Reviewer: checking tool trace coverage…")
            judgment = extract_json_object(_judge_raw())
        except RuntimeError as exc:
            out.error = f"Coverage judge failed: {exc}"
            return out

        if not judgment:
            bad_judge_streak += 1
            out.judge_rounds.append(
                JudgeRoundInfo(
                    satisfied=False,
                    rationale="Judge returned invalid or empty JSON.",
                    feedback_for_planner="Continue: gather concrete tool evidence for every part of the question.",
                )
            )
            if bad_judge_streak >= 4:
                out.error = (
                    "Coverage judge returned invalid JSON too many times in a row. "
                    "Local models often miss strict JSON on large prompts—try a larger model, "
                    "lower OLLAMA_MAX_TRACE_CHARS, raise INVESTIGATION_PLANNER_MAX_ROUNDS only if needed, "
                    "or use Gemini or Anthropic (full prompts) instead of Ollama."
                )
                return out
            if max_phases is not None and planner_phases_run >= max_phases:
                synth_user_prefix_holder[0] = (
                    f"STOPPED_EARLY: `INVESTIGATION_MAX_PLANNER_PHASES={max_phases}` — no further planner segment. "
                    "The judge returned **invalid JSON**, so coverage could not be confirmed.\n"
                    "In your answer: summarize only tool-backed facts, state uncertainty plainly, and list "
                    "concrete follow-up tools or questions for a longer run."
                )
                out.judge_rounds.append(
                    JudgeRoundInfo(
                        satisfied=True,
                        rationale=(
                            f"Stopped: **{max_phases}** planner segment(s) max (`INVESTIGATION_MAX_PLANNER_PHASES`). "
                            "Judge output was not valid JSON; synthesizing from the trace so far."
                        ),
                        feedback_for_planner=None,
                    )
                )
                break
            _planner_append_user(
                backend,
                planner_state,
                (
                    "The automated reviewer could not parse your coverage judgment. "
                    "Continue the investigation with additional tools, then stop calling tools when ready "
                    "for another review."
                ),
            )
            phase += 1
            continue

        bad_judge_streak = 0
        satisfied = bool(judgment.get("satisfied"))
        if force_synth_after_judge:
            satisfied = True
        _emit("review_done", f"Reviewer complete: satisfied={satisfied}", satisfied=satisfied)
        rationale = str(judgment.get("rationale", "")).strip() or "(no rationale)"
        missing = judgment.get("missing_aspects")
        if not isinstance(missing, list):
            missing = []
        fb_raw = judgment.get("feedback_for_planner")
        feedback = None
        if isinstance(fb_raw, str) and fb_raw.strip():
            feedback = fb_raw.strip()
        elif not satisfied:
            feedback = (
                "The reviewer is not satisfied yet. Address these gaps with tools: "
                + "; ".join(str(x) for x in missing)
                if missing
                else "Gather additional tool evidence for the full question."
            )

        if force_synth_after_judge and max_tool_steps is not None:
            rationale = (
                rationale
                + f" [Tool-step cap reached: **{max_tool_steps}** recorded tool step(s) maximum "
                "(`INVESTIGATION_MAX_TOOL_STEPS`, default **20**) — no further planner tool calls are allowed.]"
            )

        out.judge_rounds.append(
            JudgeRoundInfo(
                satisfied=satisfied,
                rationale=rationale + (f" Missing: {missing!r}" if missing else ""),
                feedback_for_planner=None if force_synth_after_judge else (feedback if not satisfied else None),
            )
        )

        if satisfied:
            break

        if max_phases is not None and planner_phases_run >= max_phases:
            synth_user_prefix_holder[0] = (
                f"STOPPED_EARLY: `INVESTIGATION_MAX_PLANNER_PHASES={max_phases}` — **no further planner segment** "
                "will run. The coverage judge was **not satisfied** with the evidence so far.\n\n"
                f"Judge rationale: {rationale}\n"
                f"Missing aspects: {missing!r}\n"
                f"Feedback that would have gone to the planner next (integrate as caveats, gaps, and suggested "
                f"follow-ups — not as raw instructions to yourself):\n{feedback or '(none)'}\n\n"
                "Your JSON answer must still be grounded only in the tool trace, but **think further** in prose: "
                "call out unanswered angles, what another investigation pass might resolve, and specific "
                "next tools or entity ids to try. Do not pretend the investigation was complete."
            )
            out.judge_rounds.append(
                JudgeRoundInfo(
                    satisfied=True,
                    rationale=(
                        f"Stopped before another planner phase: **{max_phases}** tool-planner segment(s) maximum "
                        f"(`INVESTIGATION_MAX_PLANNER_PHASES`). Synthesizing from the tool trace gathered so far."
                    ),
                    feedback_for_planner=None,
                )
            )
            break

        _planner_append_user(
            backend,
            planner_state,
            (
                "Reviewer feedback (internal — do not treat as the end-user answer):\n"
                + (feedback or "Gather more evidence with tools for all parts of the question.")
            ),
        )
        phase += 1

    had_phase_cap_note = bool(synth_user_prefix_holder[0].strip())

    try:
        _emit("synthesis_start", "Synthesis: writing the final answer…")
        synth = extract_json_object(_synth_raw())
    except RuntimeError as exc:
        out.error = f"Synthesis failed: {exc}"
        return out

    if not synth:
        out.error = "Synthesis returned invalid or empty JSON."
        return out

    answer = str(synth.get("answer", "")).strip()
    out.synthesis_rationale = str(synth.get("rationale", "")).strip()
    out.graph_focus_node_id = _normalize_focus_node_id(synth.get("graph_focus_node_id"))

    if had_phase_cap_note:
        cap_hint = (
            " [Depth capped by INVESTIGATION_MAX_PLANNER_PHASES — use 2–4 or omit for more planner–judge cycles.]"
        )
        out.synthesis_rationale = (out.synthesis_rationale + cap_hint).strip()

    if not answer and backend in ("ollama", "anthropic"):
        try:
            if backend == "ollama":
                from src.llm.local_ollama import ollama_generate_text as _ollama_text

                pre = synth_user_prefix_holder[0].strip()
                ut = f"Investigator question:\n{out.question}\n\n"
                if pre:
                    ut += pre + "\n\n"
                ut += "Tool trace:\n" + _truncate_for_local_llm(
                    _serialize_trace_for_synthesis(out.question, out.steps),
                    min(_ollama_max_trace_chars(), 16_000),
                )
                answer = _ollama_text(
                    client,
                    model=model_name,
                    system_instruction=(
                        "You write the final investigation summary for an LTC SIU analyst. "
                        "Use only facts from the tool trace in the user message. Output markdown (no JSON, no code fences): "
                        "optional short intro paragraph; line ### Key findings then '- ' bullets (one fact per bullet, "
                        "cite node ids like Person|1004); line ### Conclusion then exactly 1–2 takeaway sentences."
                    ),
                    user_text=ut,
                    num_predict=3072,
                    json_mode=False,
                ).strip()
            else:
                from src.llm.anthropic_llm import anthropic_generate_text as _anthropic_text

                pre = synth_user_prefix_holder[0].strip()
                ut = f"Investigator question:\n{out.question}\n\n"
                if pre:
                    ut += pre + "\n\n"
                ut += "Tool trace:\n" + _serialize_trace_for_synthesis(out.question, out.steps)
                answer = _anthropic_text(
                    client,
                    model=model_name,
                    system_instruction=(
                        "You write the final investigation summary for an LTC SIU analyst. "
                        "Use only facts from the tool trace in the user message. Output markdown (no JSON, no code fences): "
                        "optional short intro paragraph; line ### Key findings then '- ' bullets (one fact per bullet, "
                        "cite node ids like Person|1004); line ### Conclusion then exactly 1–2 takeaway sentences."
                    ),
                    user_text=ut,
                    max_tokens=3072,
                ).strip()
            if answer and not out.synthesis_rationale:
                out.synthesis_rationale = "(Plain-text fallback: JSON answer was empty.)"
        except Exception:
            pass

    if not out.graph_focus_node_id:
        out.graph_focus_node_id = _normalize_focus_node_id(_first_graph_node_id_from_steps(out.steps))

    out.final_text = answer or "(Synthesis produced an empty answer.)"
    _emit("synthesis_done", "Done.")

    return out
