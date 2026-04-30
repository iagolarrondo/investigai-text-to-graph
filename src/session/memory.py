from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from src.app.investigation_graph import gather_investigation_anchors
from src.llm.tool_agent import ToolAgentResult


@dataclass(frozen=True)
class SessionTurn:
    turn_id: int
    created_at_utc: str
    user_question: str
    investigation_question: str
    final_answer: str
    graph_focus_node_id: str | None
    anchors: list[str]
    reviewer_notes: list[str]
    synthesis_rationale: str


@dataclass(frozen=True)
class MemoryDigest:
    turn_count: int
    recent_questions: list[str]
    recent_focus_node_ids: list[str]
    recent_anchor_ids: list[str]
    latest_answer_excerpt: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _reviewer_notes(tr: ToolAgentResult, *, max_items: int = 2, max_chars: int = 260) -> list[str]:
    out: list[str] = []
    for jr in (getattr(tr, "judge_rounds", None) or []):
        if not jr.satisfied:
            txt = (jr.feedback_for_planner or jr.rationale or "").strip()
            if txt:
                out.append(txt[:max_chars])
        if len(out) >= max_items:
            break
    return out


def _answer_excerpt(text: str, *, max_chars: int = 420) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def build_turn_from_result(
    *,
    turn_id: int,
    user_question: str,
    investigation_question: str,
    result: ToolAgentResult,
) -> SessionTurn:
    anchors = sorted(gather_investigation_anchors(result))
    return SessionTurn(
        turn_id=turn_id,
        created_at_utc=_utc_now_iso(),
        user_question=(user_question or "").strip(),
        investigation_question=(investigation_question or "").strip(),
        final_answer=(result.final_text or "").strip(),
        graph_focus_node_id=(result.graph_focus_node_id or None),
        anchors=anchors[:25],
        reviewer_notes=_reviewer_notes(result),
        synthesis_rationale=(result.synthesis_rationale or "").strip(),
    )


def build_memory_digest(turns: list[dict[str, Any]] | list[SessionTurn], *, last_n: int = 3) -> MemoryDigest:
    rows: list[SessionTurn] = []
    for t in turns[-max(1, last_n) :]:
        if isinstance(t, SessionTurn):
            rows.append(t)
        elif isinstance(t, dict):
            rows.append(SessionTurn(**t))
    if not rows:
        return MemoryDigest(
            turn_count=0,
            recent_questions=[],
            recent_focus_node_ids=[],
            recent_anchor_ids=[],
            latest_answer_excerpt="",
        )
    focus = [x.graph_focus_node_id for x in rows if x.graph_focus_node_id]
    anchors: list[str] = []
    for r in rows:
        anchors.extend(r.anchors[:8])
    dedup_anchors = list(dict.fromkeys(anchors))
    return MemoryDigest(
        turn_count=len(turns),
        recent_questions=[r.user_question for r in rows],
        recent_focus_node_ids=list(dict.fromkeys(focus)),
        recent_anchor_ids=dedup_anchors[:20],
        latest_answer_excerpt=_answer_excerpt(rows[-1].final_answer),
    )


def serialize_turn(turn: SessionTurn) -> dict[str, Any]:
    return asdict(turn)

