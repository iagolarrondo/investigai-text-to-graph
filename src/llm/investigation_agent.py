"""
Multi-step **agentic** investigation: run the graph under one intent per step,
ask a coverage judge whether the user’s question is fully addressed, optionally
run further intents, then synthesize one answer from all steps.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

try:
    from dotenv import load_dotenv
    from pathlib import Path

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

import anthropic

from src.llm.prompts import SYSTEM_AGENTIC_SYNTHESIS, SYSTEM_COVERAGE_JUDGE
from src.llm.result_serialize import payload_to_text
from src.llm.router import (
    DEFAULT_CLAIM_NODE_ID,
    RouterDecision,
    VALID_INTENTS,
    claim_anchor_is_valid,
    dispatch_routed_query,
    extract_claim_node_id,
)

StoppedReason = Literal[
    "satisfied",
    "max_steps",
    "duplicate",
    "no_next",
    "unknown_first",
    "error",
    "no_api",
]


@dataclass
class CoverageJudgment:
    satisfied: bool
    missing_aspects: list[str]
    next_intent: str | None
    claim_node_id: str | None
    rationale: str


@dataclass
class InvestigationStepRecord:
    step_index: int
    decision: RouterDecision
    dispatch: dict[str, Any]

    def signature(self) -> tuple[str, str | None]:
        cid = self.decision.claim_node_id
        return (self.decision.intent, cid)


@dataclass
class AgentRunResult:
    question: str
    steps: list[InvestigationStepRecord] = field(default_factory=list)
    stopped_reason: StoppedReason = "satisfied"
    stop_detail: str = ""
    judge_notes: list[str] = field(default_factory=list)
    synthesis: str = ""
    error: str | None = None


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _parse_judgment(raw: str) -> CoverageJudgment | None:
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        return None
    satisfied = bool(data.get("satisfied"))
    missing = data.get("missing_aspects")
    if not isinstance(missing, list):
        missing = []
    missing = [str(x) for x in missing]
    nxt = data.get("next_intent")
    if nxt in (None, "null", ""):
        next_intent = None
    else:
        next_intent = str(nxt) if str(nxt) in VALID_INTENTS else None
    cid = data.get("claim_node_id")
    if cid in (None, "null", ""):
        claim_node_id = None
    else:
        claim_node_id = str(cid)
    rationale = str(data.get("rationale", "")).strip() or "(no rationale)"
    return CoverageJudgment(
        satisfied=satisfied,
        missing_aspects=missing,
        next_intent=next_intent,
        claim_node_id=claim_node_id,
        rationale=rationale,
    )


def _serialize_steps_for_judge(
    question: str,
    steps: list[InvestigationStepRecord],
) -> str:
    parts: list[str] = [f"User question:\n{question}\n"]
    for rec in steps:
        d = rec.dispatch
        kind = str(d.get("kind", "error"))
        decision = d.get("decision")
        payload = d.get("payload")
        lines = [f"--- Step {rec.step_index + 1} ---", f"Template (intent): `{kind}`"]
        if isinstance(decision, RouterDecision):
            lines.append(f"Routing reason: {decision.reason}")
            if decision.claim_node_id:
                lines.append(f"Claim node id: {decision.claim_node_id}")
        if d.get("error"):
            lines.append(f"Error: {d['error']}")
        lines.append("Results summary (tabular excerpt):")
        if kind not in ("unknown", "error") and payload is not None:
            lines.append(payload_to_text(kind, payload))
        else:
            lines.append("(no payload)")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def coverage_judge(
    question: str,
    steps: list[InvestigationStepRecord],
) -> CoverageJudgment | None:
    """Ask Claude whether the accumulated steps cover the user question."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    user_content = _serialize_steps_for_judge(question, steps)
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_COVERAGE_JUDGE,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        return _parse_judgment(raw)
    except Exception:
        return None


def _decision_from_judgment(
    question: str,
    j: CoverageJudgment,
) -> RouterDecision | None:
    if not j.next_intent or j.next_intent not in VALID_INTENTS:
        return None
    intent = j.next_intent
    cid: str | None
    if intent in ("claim_network", "claim_subgraph"):
        raw = (j.claim_node_id or "").strip() or extract_claim_node_id(question)
        if raw and not claim_anchor_is_valid(raw):
            # Judge must never pass Person|… / Policy|… as a claim id
            return None
        cid = raw or DEFAULT_CLAIM_NODE_ID
        if not claim_anchor_is_valid(cid):
            return None
    else:
        cid = None
    return RouterDecision(
        intent=intent,  # type: ignore[arg-type]
        claim_node_id=cid,
        source="llm",
        reason=f"Agent follow-up: {j.rationale}",
        matched_keywords=("agent",),
    )


def _is_duplicate(
    sigs: set[tuple[str, str | None]],
    decision: RouterDecision,
) -> bool:
    cid = decision.claim_node_id if decision.intent in ("claim_network", "claim_subgraph") else None
    return (decision.intent, cid) in sigs


def synthesize_agentic_answer(
    question: str,
    steps: list[InvestigationStepRecord],
) -> str:
    """Single cohesive answer from all investigation steps."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not steps:
        return ""

    blocks: list[str] = []
    for rec in steps:
        d = rec.dispatch
        kind = str(d.get("kind", ""))
        decision = d.get("decision")
        payload = d.get("payload")
        header = f"### Step {rec.step_index + 1}: template `{kind}`\n"
        if isinstance(decision, RouterDecision):
            header += f"Routing: {decision.reason}\n"
        if d.get("error"):
            header += f"Error: {d['error']}\n"
        if kind not in ("unknown", "error") and payload is not None:
            body = payload_to_text(kind, payload)
        else:
            body = "(no data)"
        blocks.append(header + "\nGraph query results:\n" + body)

    user_content = f"User question:\n{question}\n\n---\n\n" + "\n\n".join(blocks)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=SYSTEM_AGENTIC_SYNTHESIS,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text.strip()
    except Exception:
        return ""


def run_investigation_agent(
    question: str,
    first_decision: RouterDecision,
    *,
    max_steps: int = 4,
) -> AgentRunResult:
    """
    Run ``dispatch_routed_query`` in a loop: after each step, ask the coverage judge
    whether to continue with another intent.

    ``first_decision`` is typically from :func:`route_question_auto` or the UI manual template.
    """
    out = AgentRunResult(question=question)
    if max_steps < 1:
        out.stopped_reason = "error"
        out.error = "max_steps must be >= 1"
        return out

    if not os.environ.get("ANTHROPIC_API_KEY"):
        out.stopped_reason = "no_api"
        out.stop_detail = "ANTHROPIC_API_KEY is not set; agent loop requires the judge and synthesis."
        out.error = out.stop_detail
        return out

    current = first_decision
    sigs: set[tuple[str, str | None]] = set()

    for step_i in range(max_steps):
        if _is_duplicate(sigs, current):
            out.stopped_reason = "duplicate"
            out.stop_detail = "Next step would repeat an intent/claim pair already run."
            break

        cid = current.claim_node_id if current.intent in ("claim_network", "claim_subgraph") else None
        sigs.add((current.intent, cid))

        dispatch = dispatch_routed_query(current)
        rec = InvestigationStepRecord(step_index=step_i, decision=current, dispatch=dispatch)
        out.steps.append(rec)

        kind = dispatch.get("kind")
        if kind == "unknown":
            out.stopped_reason = "unknown_first"
            out.stop_detail = dispatch.get("error") or "Could not map to a template."
            break
        if kind == "error" or dispatch.get("error"):
            out.stopped_reason = "error"
            out.stop_detail = str(dispatch.get("error", "Graph error"))
            break

        if step_i >= max_steps - 1:
            out.stopped_reason = "max_steps"
            out.stop_detail = f"Reached max_steps={max_steps}."
            break

        j = coverage_judge(question, out.steps)
        if j is None:
            out.stopped_reason = "error"
            out.stop_detail = "Coverage judge failed (API or parse error)."
            out.judge_notes.append(out.stop_detail)
            break

        out.judge_notes.append(j.rationale)
        if j.satisfied:
            out.stopped_reason = "satisfied"
            out.stop_detail = j.rationale
            break

        nxt = _decision_from_judgment(question, j)
        if nxt is None:
            out.stopped_reason = "no_next"
            cid_raw = (j.claim_node_id or "").strip()
            if j.next_intent in ("claim_network", "claim_subgraph") and cid_raw and not claim_anchor_is_valid(cid_raw):
                out.stop_detail = (
                    f"Judge proposed {j.next_intent} with {cid_raw!r}, which is not a Claim node—skipped. "
                    "Person/policy questions need **Planner** mode or non-claim templates, not a claim anchor."
                )
            else:
                out.stop_detail = j.rationale
            break

        if _is_duplicate(sigs, nxt):
            out.stopped_reason = "duplicate"
            out.stop_detail = "Judge proposed a template already executed."
            break

        current = nxt

    out.synthesis = synthesize_agentic_answer(question, out.steps)
    return out
