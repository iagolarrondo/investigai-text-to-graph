from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.app.investigation_graph import gather_investigation_anchors
from src.llm.tool_agent import ToolAgentResult
from src.session.node_id_canonical import canonicalize_id_list, canonicalize_referents_dict, resolve_node_id_to_graph
from src.session.report import summarize_answer_bullets


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
    active_referents: dict[str, str | None] = field(default_factory=dict)
    answer_summary_bullets: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryDigest:
    turn_count: int
    recent_questions: list[str]
    recent_focus_node_ids: list[str]
    recent_anchor_ids: list[str]
    latest_answer_excerpt: str
    active_primary_person: str | None
    active_primary_claim: str | None
    active_primary_policy: str | None
    last_graph_focus: str | None


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


def _node_type_prefix(node_id: str) -> str:
    s = (node_id or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("person|") or low.startswith("person_"):
        return "person"
    if low.startswith("claim|") or low.startswith("claim_"):
        return "claim"
    if low.startswith("policy|") or low.startswith("policy_"):
        return "policy"
    if low.startswith("bank") or "bank_" in low[:16]:
        return "bank"
    if low.startswith("address|") or low.startswith("address_"):
        return "address"
    if low.startswith("business|") or low.startswith("business_"):
        return "business"
    return ""


def infer_active_referents(
    anchors: list[str],
    graph_focus_node_id: str | None,
) -> dict[str, str | None]:
    """Deterministic primary entities for pronoun / follow-up resolution."""
    primary_person: str | None = None
    primary_claim: str | None = None
    primary_policy: str | None = None
    primary_bank: str | None = None

    ordered = list(dict.fromkeys(a for a in anchors if a))
    for a in ordered:
        kind = _node_type_prefix(a)
        if kind == "person" and not primary_person:
            primary_person = a
        elif kind == "claim" and not primary_claim:
            primary_claim = a
        elif kind == "policy" and not primary_policy:
            primary_policy = a
        elif kind == "bank" and not primary_bank:
            primary_bank = a

    focus = (graph_focus_node_id or "").strip() or None
    if focus:
        fk = _node_type_prefix(focus)
        if fk == "person":
            primary_person = primary_person or focus
        elif fk == "claim":
            primary_claim = primary_claim or focus
        elif fk == "policy":
            primary_policy = primary_policy or focus
        elif fk == "bank":
            primary_bank = primary_bank or focus

    return {
        "primary_person": primary_person,
        "primary_claim": primary_claim,
        "primary_policy": primary_policy,
        "primary_bank": primary_bank,
        "graph_focus": focus,
    }


def merge_session_referents(
    prev: dict[str, str | None] | None,
    turn_refs: dict[str, str | None],
) -> dict[str, str | None]:
    """Rolling session referents: graph-canonical new values override; invalid updates are skipped."""
    out: dict[str, str | None] = dict(prev or {})
    try:
        from src.graph_query.query_graph import get_graph

        G = get_graph()
        raw_updates = {k: str(v).strip() for k, v in (turn_refs or {}).items() if v and str(v).strip()}
        canon_updates = canonicalize_referents_dict(raw_updates, G)
        for k, v in canon_updates.items():
            if v:
                out[k] = v
        return canonicalize_referents_dict(out, G)
    except RuntimeError:
        for k, v in (turn_refs or {}).items():
            if v and str(v).strip():
                out[k] = str(v).strip()
        return {k: v for k, v in out.items() if v}


def _session_turn_from_row(t: Any) -> SessionTurn:
    if isinstance(t, SessionTurn):
        return t
    if not isinstance(t, dict):
        raise TypeError("turn row must be dict or SessionTurn")
    d = dict(t)
    d.setdefault("active_referents", {})
    d.setdefault("answer_summary_bullets", [])
    d.setdefault("synthesis_rationale", "")
    return SessionTurn(**d)


def build_turn_from_result(
    *,
    turn_id: int,
    user_question: str,
    investigation_question: str,
    result: ToolAgentResult,
) -> SessionTurn:
    anchors_raw = sorted(gather_investigation_anchors(result))
    try:
        from src.graph_query.query_graph import get_graph

        G = get_graph()
        anchors = canonicalize_id_list(anchors_raw, G)
        fr = (result.graph_focus_node_id or "").strip()
        focus = resolve_node_id_to_graph(fr, G) if fr else None
    except RuntimeError:
        G = None
        anchors = anchors_raw
        focus = (result.graph_focus_node_id or "").strip() or None
    refs = infer_active_referents(anchors, focus)
    if G is not None:
        refs = canonicalize_referents_dict(refs, G)
    bullets = summarize_answer_bullets(result.final_text or "", max_bullets=5)
    return SessionTurn(
        turn_id=turn_id,
        created_at_utc=_utc_now_iso(),
        user_question=(user_question or "").strip(),
        investigation_question=(investigation_question or "").strip(),
        final_answer=(result.final_text or "").strip(),
        graph_focus_node_id=focus,
        anchors=anchors[:25],
        reviewer_notes=_reviewer_notes(result),
        synthesis_rationale=(result.synthesis_rationale or "").strip(),
        active_referents=refs,
        answer_summary_bullets=bullets,
    )


def build_memory_digest(turns: list[dict[str, Any]] | list[SessionTurn], *, last_n: int = 3) -> MemoryDigest:
    rows: list[SessionTurn] = []
    for t in turns[-max(1, last_n) :]:
        rows.append(_session_turn_from_row(t))
    if not rows:
        return MemoryDigest(
            turn_count=len(turns),
            recent_questions=[],
            recent_focus_node_ids=[],
            recent_anchor_ids=[],
            latest_answer_excerpt="",
            active_primary_person=None,
            active_primary_claim=None,
            active_primary_policy=None,
            last_graph_focus=None,
        )
    focus = [x.graph_focus_node_id for x in rows if x.graph_focus_node_id]
    anchors: list[str] = []
    for r in rows:
        anchors.extend(r.anchors[:8])
    dedup_anchors = list(dict.fromkeys(anchors))

    last = rows[-1]
    ref = dict(last.active_referents or {})
    G = None
    try:
        from src.graph_query.query_graph import get_graph

        G = get_graph()
        dedup_anchors = canonicalize_id_list(dedup_anchors, G)
        focus = [f for f in (resolve_node_id_to_graph(str(f), G) for f in focus if f) if f]
        focus = list(dict.fromkeys(focus))
        ref = canonicalize_referents_dict(ref, G)
    except RuntimeError:
        pass

    last_graph_focus = ref.get("graph_focus") or last.graph_focus_node_id
    if G is not None and last_graph_focus:
        last_graph_focus = resolve_node_id_to_graph(str(last_graph_focus), G)

    return MemoryDigest(
        turn_count=len(turns),
        recent_questions=[r.user_question for r in rows],
        recent_focus_node_ids=list(dict.fromkeys(focus)),
        recent_anchor_ids=dedup_anchors[:20],
        latest_answer_excerpt=_answer_excerpt(last.final_answer),
        active_primary_person=ref.get("primary_person"),
        active_primary_claim=ref.get("primary_claim"),
        active_primary_policy=ref.get("primary_policy"),
        last_graph_focus=last_graph_focus,
    )


def serialize_turn(turn: SessionTurn) -> dict[str, Any]:
    return asdict(turn)
