from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

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
    active_referents: dict[str, Any] = field(default_factory=dict)
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
    active_primary_bank: str | None
    active_primary_business: str | None
    active_primary_address: str | None
    last_graph_focus: str | None
    # All graph node ids from recent turns' anchors + focus, keyed by node kind (person, claim, …).
    recent_entity_ids_by_kind: dict[str, tuple[str, ...]]


_KIND_ORDER: tuple[str, ...] = ("person", "claim", "policy", "bank", "business", "address")
_MAX_IDS_PER_REF_KEY = 50


def _rollup_entity_ids_for_digest(rows: list[SessionTurn], G: Any | None) -> dict[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = {k: [] for k in _KIND_ORDER}
    seen: dict[str, set[str]] = {k: set() for k in _KIND_ORDER}

    def tack(kind: str, raw_id: str | None) -> None:
        if not kind or kind not in buckets:
            return
        nid = (raw_id or "").strip()
        if not nid:
            return
        if G is not None:
            nid = resolve_node_id_to_graph(nid, G) or nid
        if nid not in seen[kind]:
            seen[kind].add(nid)
            buckets[kind].append(nid)

    for r in rows:
        tack(_node_type_prefix(r.graph_focus_node_id or ""), r.graph_focus_node_id)
        for aid in (r.anchors or [])[:25]:
            tack(_node_type_prefix(aid), aid)
        ar = r.active_referents or {}
        for kind in _KIND_ORDER:
            key = f"ids_{kind}"
            v = ar.get(key)
            if isinstance(v, list):
                for x in v:
                    tack(kind, str(x).strip() if x else "")
            pk = ar.get(f"primary_{kind}")
            if pk and not isinstance(pk, list):
                tack(kind, str(pk).strip())
    return {k: tuple(v[:_MAX_IDS_PER_REF_KEY]) for k, v in buckets.items() if v}


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
) -> dict[str, Any]:
    """Deterministic primary entities plus full per-type id lists from anchors + focus."""
    buckets: dict[str, list[str]] = {k: [] for k in _KIND_ORDER}
    seen: dict[str, set[str]] = {k: set() for k in _KIND_ORDER}

    def add_id(kind: str, raw: str | None) -> None:
        if not kind or kind not in buckets:
            return
        nid = (raw or "").strip()
        if not nid:
            return
        if nid not in seen[kind]:
            seen[kind].add(nid)
            buckets[kind].append(nid)

    ordered = list(dict.fromkeys(a for a in anchors if a))
    focus = (graph_focus_node_id or "").strip() or None
    if focus:
        add_id(_node_type_prefix(focus), focus)
    for a in ordered:
        add_id(_node_type_prefix(a), a)

    out: dict[str, Any] = {
        "primary_person": buckets["person"][0] if buckets["person"] else None,
        "primary_claim": buckets["claim"][0] if buckets["claim"] else None,
        "primary_policy": buckets["policy"][0] if buckets["policy"] else None,
        "primary_bank": buckets["bank"][0] if buckets["bank"] else None,
        "primary_business": buckets["business"][0] if buckets["business"] else None,
        "primary_address": buckets["address"][0] if buckets["address"] else None,
        "graph_focus": focus,
    }
    for kind in _KIND_ORDER:
        if buckets[kind]:
            out[f"ids_{kind}"] = buckets[kind][: _MAX_IDS_PER_REF_KEY]
    return out


def extend_referents_with_node_ids(
    refs: dict[str, Any],
    *,
    additional_ids: Iterable[str] | None = None,
    priority_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Merge extra graph node ids (e.g. ER disambiguation candidates) into ``ids_*``.

    Per kind, order is: ``priority_ids`` (user selections) first, then other
    ``additional_ids`` (typically all candidates), then ids already in ``refs``.
    """
    out = dict(refs)
    pri = [str(x).strip() for x in (priority_ids or []) if x and str(x).strip()]
    add = [str(x).strip() for x in (additional_ids or []) if x and str(x).strip()]
    pri_set = set(pri)

    for kind in _KIND_ORDER:
        key = f"ids_{kind}"
        seed: list[str] = []
        cur = out.get(key)
        if isinstance(cur, list):
            for x in cur:
                sx = str(x).strip()
                if sx:
                    seed.append(sx)
        pk = out.get(f"primary_{kind}")
        if pk and not isinstance(pk, list):
            ps = str(pk).strip()
            if ps and ps not in seed:
                seed.insert(0, ps)
        seed = list(dict.fromkeys(seed))
        pri_k = [x for x in pri if _node_type_prefix(x) == kind]
        add_k = [x for x in add if _node_type_prefix(x) == kind and x not in pri_set]
        head = list(dict.fromkeys(pri_k + add_k))
        head_set = set(head)
        tail = [x for x in seed if x not in head_set]
        merged = (head + tail)[:_MAX_IDS_PER_REF_KEY]
        if merged:
            out[key] = merged
    return out


def merge_session_referents(
    prev: dict[str, Any] | None,
    turn_refs: dict[str, Any],
) -> dict[str, Any]:
    """Rolling session referents: graph-canonical new values override; list ids merge newest-first."""
    out: dict[str, Any] = dict(prev or {})
    try:
        from src.graph_query.query_graph import get_graph

        G = get_graph()
        raw_updates = dict(turn_refs or {})
        canon_updates = canonicalize_referents_dict(raw_updates, G)
        for k, v in canon_updates.items():
            if isinstance(v, list):
                prev_v = out.get(k)
                prev_list = list(prev_v) if isinstance(prev_v, list) else ([] if not prev_v else [str(prev_v)])
                merged = list(dict.fromkeys(list(v) + prev_list))[:_MAX_IDS_PER_REF_KEY]
                out[k] = merged
            elif v:
                out[k] = v
        return canonicalize_referents_dict(out, G)
    except RuntimeError:
        for k, v in (turn_refs or {}).items():
            if isinstance(v, list):
                prev_v = out.get(k)
                prev_list = list(prev_v) if isinstance(prev_v, list) else ([] if not prev_v else [str(prev_v)])
                merged = list(dict.fromkeys([str(x) for x in v if x] + prev_list))[:_MAX_IDS_PER_REF_KEY]
                out[k] = merged
            elif v and str(v).strip():
                out[k] = str(v).strip()
        return out


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
            active_primary_bank=None,
            active_primary_business=None,
            active_primary_address=None,
            last_graph_focus=None,
            recent_entity_ids_by_kind={},
        )
    focus = [x.graph_focus_node_id for x in rows if x.graph_focus_node_id]
    anchors: list[str] = []
    for r in rows:
        anchors.extend(r.anchors[:8])
    dedup_anchors = list(dict.fromkeys(anchors))

    last = rows[-1]
    ref = dict(last.active_referents or {})
    inferred = infer_active_referents(list(last.anchors or []), last.graph_focus_node_id)
    for k, v in inferred.items():
        if isinstance(v, list):
            if not v:
                continue
            existing = ref.get(k)
            if isinstance(existing, list):
                ref[k] = list(dict.fromkeys(list(v) + list(existing)))[:_MAX_IDS_PER_REF_KEY]
            elif not existing:
                ref[k] = v
        elif v and not ref.get(k):
            ref[k] = v
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

    rollup = _rollup_entity_ids_for_digest(rows, G)

    return MemoryDigest(
        turn_count=len(turns),
        recent_questions=[r.user_question for r in rows],
        recent_focus_node_ids=list(dict.fromkeys(focus)),
        recent_anchor_ids=dedup_anchors[:20],
        latest_answer_excerpt=_answer_excerpt(last.final_answer),
        active_primary_person=ref.get("primary_person"),
        active_primary_claim=ref.get("primary_claim"),
        active_primary_policy=ref.get("primary_policy"),
        active_primary_bank=ref.get("primary_bank"),
        active_primary_business=ref.get("primary_business"),
        active_primary_address=ref.get("primary_address"),
        last_graph_focus=last_graph_focus,
        recent_entity_ids_by_kind=rollup,
    )


def serialize_turn(turn: SessionTurn) -> dict[str, Any]:
    return asdict(turn)
