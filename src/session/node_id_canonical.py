"""
Canonicalize graph node ids for session memory.

Tool traces and synthesis may mix ``Person|5063``-style ids with CSV-native ids
like ``person_5063``. Session memory must store only ids that exist in the
loaded NetworkX graph, with a single canonical string per logical node.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# (pipe prefix, underscore-style lowercase prefix used in many CSV exports)
_TYPE_ALIASES: tuple[tuple[str, str], ...] = (
    ("Person", "person"),
    ("Claim", "claim"),
    ("Policy", "policy"),
    ("Address", "address"),
    ("Business", "business"),
    ("BankAccount", "bank"),
)


def node_id_variants(node_id: str) -> list[str]:
    """All plausible string variants for the same logical node id."""
    s = (node_id or "").strip()
    if not s:
        return []
    out: list[str] = [s]

    for pipe_p, snake_p in _TYPE_ALIASES:
        m = re.match(rf"^{re.escape(pipe_p)}\|(.+)$", s, re.IGNORECASE)
        if m:
            tail = m.group(1).strip()
            if tail:
                out.append(f"{snake_p}_{tail}")
        m2 = re.match(rf"^{re.escape(snake_p)}_([A-Za-z0-9_.-]+)$", s, re.IGNORECASE)
        if m2:
            tail2 = m2.group(1).strip()
            if tail2:
                out.append(f"{pipe_p}|{tail2}")

    return list(dict.fromkeys(out))


def _prefer_graph_id(hits: list[str]) -> str:
    """If several variants exist as nodes, prefer CSV-style ids without ``|``."""
    if len(hits) == 1:
        return hits[0]
    no_pipe = [h for h in hits if "|" not in h]
    if no_pipe:
        return no_pipe[0]
    return hits[0]


def resolve_node_id_to_graph(node_id: str, G: Any) -> str | None:
    """Return the graph key for ``node_id``, or None if no variant exists in ``G``."""
    s = (node_id or "").strip()
    if not s:
        return None
    hits = [v for v in node_id_variants(s) if v in G]
    if not hits:
        return None
    return _prefer_graph_id(hits)


def canonicalize_id_list(ids: Iterable[str], G: Any) -> list[str]:
    """
    Map each raw id to a graph node id when possible; drop unknowns; dedupe by resolved id.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in ids:
        s = (raw or "").strip()
        if not s:
            continue
        canon = resolve_node_id_to_graph(s, G)
        if canon:
            if canon not in seen:
                seen.add(canon)
                out.append(canon)
        elif s in G:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def canonicalize_referents_dict(refs: dict[str, str | None], G: Any) -> dict[str, str | None]:
    """
    Keep only referent values that resolve to a node in ``G``.
    Multiple keys may end up with the same canonical id (allowed).
    """
    out: dict[str, str | None] = {}
    for k, v in (refs or {}).items():
        if not v or not str(v).strip():
            continue
        canon = resolve_node_id_to_graph(str(v).strip(), G)
        if canon:
            out[k] = canon
    return out


def canonicalize_turn_dict_for_storage(row: dict[str, Any], G: Any) -> dict[str, Any]:
    """Return a shallow-updated copy of a serialized turn with graph-canonical ids."""
    r = dict(row)
    anchors = r.get("anchors") or []
    if isinstance(anchors, list):
        r["anchors"] = canonicalize_id_list([str(a) for a in anchors if a], G)
    gf = r.get("graph_focus_node_id")
    if isinstance(gf, str) and gf.strip():
        c = resolve_node_id_to_graph(gf.strip(), G)
        r["graph_focus_node_id"] = c
    else:
        r["graph_focus_node_id"] = None
    ar = r.get("active_referents")
    if isinstance(ar, dict):
        r["active_referents"] = canonicalize_referents_dict(ar, G)
    return r
