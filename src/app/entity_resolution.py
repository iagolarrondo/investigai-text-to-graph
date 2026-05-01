"""
Entity resolution helpers for the Streamlit UI.

This module stays deterministic with respect to the loaded graph:
- Candidate lists come from `query_graph.search_nodes`.
- Question rewriting is a pure string transform based on user selections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.graph_query.query_graph import search_nodes
from src.session.node_id_canonical import resolve_node_id_to_graph


@dataclass(frozen=True)
class Mention:
    mention: str
    node_type_hint: str | None = None


@dataclass(frozen=True)
class Candidate:
    node_id: str
    node_type: str
    label: str
    match_reason: str


def fallback_mentions(question: str) -> list[dict[str, str | None]]:
    """
    Deterministic mention extraction when the LLM extractor returns nothing.

    Supports:
    - Places like \"Quincy, MA\" (Address hint)
    - Two-word capitalized names like \"Emma Webb\" (Person hint)
    """
    q = (question or "").strip()
    if not q:
        return []

    out: list[dict[str, str | None]] = []

    def add(mention: str, hint: str | None) -> None:
        mention = (mention or "").strip()
        if not mention or mention not in q:
            return
        for row in out:
            if row.get("mention") == mention:
                return
        out.append({"mention": mention, "node_type_hint": hint})

    # City, ST
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*,\s*([A-Z]{2})\b", q):
        add(m.group(0), "Address")

    # Capitalized First Last
    for m in re.finditer(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b", q):
        add(m.group(0), "Person")

    return out[:5]


def candidate_nodes(*, mention: str, node_type_hint: str | None, limit: int = 25) -> list[Candidate]:
    """
    Return up to `limit` candidates from `search_nodes` for a mention.

    Strategy:
    - Try node_type filter first when provided.
    - If no matches, retry without node_type filter.
    """
    q = (mention or "").strip()
    if not q:
        return []

    def _alt_queries(s: str) -> list[str]:
        """
        Generate a few normalized variants for better matching.

        Example: \"Quincy, MA\" -> [\"Quincy, MA\", \"Quincy MA\", \"Quincy\", \"MA\"]
        """
        base = (s or "").strip()
        if not base:
            return []
        out: list[str] = []

        def add(x: str) -> None:
            x = (x or "").strip()
            if x and x not in out:
                out.append(x)

        add(base)
        # Replace punctuation with spaces and collapse whitespace.
        spaced = re.sub(r"[^A-Za-z0-9]+", " ", base)
        spaced = re.sub(r"\s+", " ", spaced).strip()
        add(spaced)
        # Token fallbacks (only if short list).
        toks = [t for t in spaced.split(" ") if t]
        if 1 < len(toks) <= 4:
            for t in toks:
                add(t)
        return out

    def to_candidates(obj: dict[str, Any]) -> list[Candidate]:
        df = obj.get("matches")
        out: list[Candidate] = []
        if df is None:
            return out
        try:
            rows = df.to_dict(orient="records")  # pandas
        except Exception:
            return out
        for r in rows[: max(1, min(limit, 200))]:
            out.append(
                Candidate(
                    node_id=str(r.get("node_id", "")).strip(),
                    node_type=str(r.get("node_type", "")).strip(),
                    label=str(r.get("label", "")).strip(),
                    match_reason=str(r.get("match_reason", "")).strip(),
                )
            )
        return [c for c in out if c.node_id]

    # Try a few query variants, preferring type-filtered results first.
    for qq in _alt_queries(q):
        res = (
            search_nodes(qq, node_type=node_type_hint, limit=max(limit, 25))
            if node_type_hint
            else search_nodes(qq, limit=max(limit, 25))
        )
        cands = to_candidates(res)
        if cands:
            return cands[:limit]

    if node_type_hint:
        for qq in _alt_queries(q):
            res2 = search_nodes(qq, limit=max(limit, 25))
            c2 = to_candidates(res2)
            if c2:
                return c2[:limit]

    return []


def format_candidate_option(c: Candidate) -> str:
    lab = c.label or "(no label)"
    nt = c.node_type or "Unknown"
    return f"{nt} • {lab} • {c.node_id}"


def rewrite_question(question: str, replacements: dict[str, str]) -> str:
    """
    Replace each mention substring with the chosen node id.

    - Replacements are applied longest-mention-first to reduce overlap issues.
    - Uses literal substring replacement (case-sensitive) on the original mention text.
    """
    q = question or ""
    items = [(k, v) for k, v in (replacements or {}).items() if k and v]
    items.sort(key=lambda kv: len(kv[0]), reverse=True)
    for mention, node_id in items:
        q = q.replace(mention, node_id)
    return q


_NODE_ID_TOKEN_RE = re.compile(
    r"\b([A-Za-z]+\|[A-Za-z0-9_.-]+|[A-Za-z0-9_]+_[A-Za-z0-9_.-]+)\b"
)


def question_already_has_node_ids(question: str) -> bool:
    """Heuristic: if the question already contains node-id-like tokens, skip mention extraction."""
    return bool(_NODE_ID_TOKEN_RE.search(question or ""))


def _span_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    s1, e1 = a
    s2, e2 = b
    return s1 < e2 and s2 < e1


def verified_graph_anchor_spans(question: str, G: Any) -> list[tuple[int, int, str]]:
    """
    Spans of node-id-like tokens that **resolve** to an existing node in ``G``,
    plus the canonical graph id for each span.
    """
    q = question or ""
    out: list[tuple[int, int, str]] = []
    for m in _NODE_ID_TOKEN_RE.finditer(q):
        raw = m.group(0).strip()
        if not raw:
            continue
        canon = resolve_node_id_to_graph(raw, G)
        if canon:
            out.append((m.start(), m.end(), canon))
    return out


def filter_mentions_excluding_graph_anchors(
    question: str,
    mentions: list[dict[str, str | None]],
    G: Any,
) -> list[dict[str, str | None]]:
    """
    Drop mentions whose resolved span overlaps a **verified** graph node-id span,
    so substrings like ``person`` inside ``person_5056`` are not re-searched as names.
    """
    spans = verified_graph_anchor_spans(question, G)
    if not spans:
        return list(mentions or [])

    kept: list[dict[str, str | None]] = []
    for row in mentions or []:
        mention_raw = str(row.get("mention", "")).strip()
        if not mention_raw:
            continue
        mspan = locate_mention_span(question, mention_raw)
        if mspan is None:
            kept.append(row)
            continue
        if any(_span_overlap(mspan, (vs[0], vs[1])) for vs in spans):
            continue
        kept.append(row)
    return kept


def verified_graph_node_ids_in_question(question: str, G: Any) -> list[str]:
    """Ordered unique canonical ids for graph-resolvable node-id tokens in ``question``."""
    seen: set[str] = set()
    out: list[str] = []
    for _s, _e, cid in verified_graph_anchor_spans(question, G):
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def unresolved_graph_like_id_tokens(question: str, G: Any) -> list[str]:
    """Id-like tokens that do **not** resolve to any node in ``G``."""
    bad: list[str] = []
    q = question or ""
    for m in _NODE_ID_TOKEN_RE.finditer(q):
        raw = m.group(0).strip()
        if raw and resolve_node_id_to_graph(raw, G) is None:
            bad.append(raw)
    return list(dict.fromkeys(bad))


def append_verified_graph_node_hint(question: str, G: Any) -> str:
    """
    Append a short instruction block so the planner treats verified ids as anchors
    and does not misinterpret them as missing after failed name search.
    """
    ids = verified_graph_node_ids_in_question(question, G)
    if not ids:
        return question
    marker = "--- Verified graph node ids ---"
    if marker in (question or ""):
        return question
    lines = "\n".join(f"- `{x}`" for x in ids)
    return (
        (question or "").rstrip()
        + "\n\n"
        + marker
        + "\n"
        + "The following ids **exist** in the loaded graph. Treat them as anchored entities; "
        + "do **not** claim they are missing or require rediscovery via name search.\n"
        + lines
    )


def locate_mention_span(question: str, mention: str) -> tuple[int, int] | None:
    """
    Find the mention inside the question.

    Tries:
    1) simple case-insensitive substring match
    2) loose match ignoring non-alphanumeric characters (helps with punctuation/spacing differences)
    """
    q = question or ""
    m = (mention or "").strip()
    if not q or not m:
        return None

    q_lower = q.lower()
    m_lower = m.lower()
    idx = q_lower.find(m_lower)
    if idx >= 0:
        return idx, idx + len(m)

    # Loose match: compare only [a-z0-9] streams, but map back to original indices.
    q_map: list[int] = []
    q_simpl: list[str] = []
    for i, ch in enumerate(q_lower):
        if ch.isalnum():
            q_map.append(i)
            q_simpl.append(ch)
    m_simpl = "".join(ch for ch in m_lower if ch.isalnum())
    if not m_simpl:
        return None
    q_simpl_s = "".join(q_simpl)
    j = q_simpl_s.find(m_simpl)
    if j < 0:
        return None
    start = q_map[j]
    end = q_map[j + len(m_simpl) - 1] + 1
    return start, end

