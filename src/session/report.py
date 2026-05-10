from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from typing import Any


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def summarize_answer_bullets(text: str, *, max_bullets: int = 5) -> list[str]:
    """
    Derive a short bullet list from synthesis markdown/plain text.
    Prefers existing '- ' / '* ' lines; otherwise splits on paragraph/sentence boundaries.
    """
    raw = (text or "").strip()
    if not raw:
        return []

    bullets: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if re.match(r"^[-*]\s+", s):
            item = re.sub(r"^[-*]\s+", "", s).strip()
            if item and item not in bullets:
                bullets.append(item)
        elif re.match(r"^###?\s+", s):
            continue
        if len(bullets) >= max_bullets:
            break

    if len(bullets) >= 2:
        return bullets[:max_bullets]

    # Fallback: first sentences / clauses
    chunk = re.sub(r"\s+", " ", raw)
    chunk = re.sub(r"^#+\s*\w+.*?(?=(?:#|\Z))", "", chunk).strip()
    parts = re.split(r"(?<=[.!?])\s+", chunk)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if len(p) < 12:
            continue
        out.append(p.rstrip("."))
        if len(out) >= max_bullets:
            break
    if not out and chunk:
        out = [chunk[:280] + ("…" if len(chunk) > 280 else "")]
    return out[:max_bullets]


def _chip_kind(node_id: str) -> str:
    s = (node_id or "").strip().lower()
    if s.startswith("person|") or s.startswith("person_"):
        return "person"
    if s.startswith("claim|") or s.startswith("claim_"):
        return "claim"
    if s.startswith("policy|") or s.startswith("policy_"):
        return "policy"
    if "bank" in s[:12]:
        return "bank"
    if s.startswith("address|") or s.startswith("address_"):
        return "address"
    if s.startswith("business|") or s.startswith("business_"):
        return "business"
    return "other"


def _chip_html(node_id: str) -> str:
    nid = escape(str(node_id).strip())
    kind = _chip_kind(nid)
    return f"<span class='chip chip-{kind}'><code>{nid}</code></span>"


def _anchors_for_display(anchors: list[Any]) -> list[str]:
    raw = [str(a) for a in (anchors or []) if a]
    try:
        from src.graph_query.query_graph import get_graph
        from src.session.node_id_canonical import canonicalize_id_list

        return canonicalize_id_list(raw, get_graph())
    except RuntimeError:
        return list(dict.fromkeys(raw))


def _focus_for_display(focus_raw: str) -> str:
    s = (focus_raw or "").strip()
    if not s:
        return ""
    try:
        from src.graph_query.query_graph import get_graph
        from src.session.node_id_canonical import resolve_node_id_to_graph

        c = resolve_node_id_to_graph(s, get_graph())
        return c or s
    except RuntimeError:
        return s


def _render_turn(turn: dict[str, Any], idx: int) -> str:
    user_question = escape(str(turn.get("user_question", "")).strip())
    inv_question = escape(str(turn.get("investigation_question", "")).strip())
    focus_raw = str(turn.get("graph_focus_node_id") or "").strip()
    focus_disp = _focus_for_display(focus_raw)
    anchors = _anchors_for_display(turn.get("anchors") or [])
    notes = [str(n) for n in (turn.get("reviewer_notes") or []) if n]
    bullets = turn.get("answer_summary_bullets")
    if not isinstance(bullets, list) or not bullets:
        bullets = summarize_answer_bullets(str(turn.get("final_answer", "")), max_bullets=5)

    inv_block = ""
    if inv_question and inv_question != user_question:
        inv_block = (
            "<div class='field'><span class='k'>Resolved question</span>"
            f"<div class='v'>{inv_question}</div></div>"
        )

    bullets_html = ""
    if bullets:
        lis = "".join(f"<li>{escape(str(b))}</li>" for b in bullets[:5])
        bullets_html = f"<div class='field'><span class='k'>Summary</span><ul class='tight'>{lis}</ul></div>"

    focus_html = ""
    if focus_disp:
        focus_html = (
            "<div class='field'><span class='k'>Graph focus</span><div class='v'>"
            f"{_chip_html(focus_disp)}</div></div>"
        )

    anchors_html = ""
    if anchors:
        chips = " ".join(_chip_html(a) for a in anchors[:12])
        anchors_html = f"<div class='field'><span class='k'>Key entities</span><div class='v chips'>{chips}</div></div>"

    caveat_html = ""
    if notes:
        caveat_html = (
            "<div class='field caveat'><span class='k'>Caveat / gap</span>"
            f"<ul class='tight'>{''.join(f'<li>{escape(n[:400])}</li>' for n in notes[:2])}</ul></div>"
        )

    full = escape(str(turn.get("final_answer", "")).strip())
    detail_html = ""
    if full and len(full) > 400:
        detail_html = (
            "<details class='detail'><summary>Full answer (detail)</summary>"
            f"<pre class='fulltext'>{full}</pre></details>"
        )

    return (
        f"<section class='turn'><div class='turn-head'><span class='turn-n'>Turn {idx}</span></div>"
        f"<div class='field'><span class='k'>User question</span><div class='v'>{user_question}</div></div>"
        f"{inv_block}"
        f"{bullets_html}"
        f"{focus_html}"
        f"{anchors_html}"
        f"{caveat_html}"
        f"{detail_html}"
        f"</section>"
    )


def build_session_report_html(turns: list[dict[str, Any]]) -> str:
    rendered_turns = "\n".join(_render_turn(t, i) for i, t in enumerate(turns, start=1))
    generated = _utc_stamp()
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>InvestigAI Session Report</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 28px;
      line-height: 1.4; color: #1a1a1a; max-width: 880px; }}
    h1 {{ font-size: 1.35rem; margin: 0 0 4px 0; font-weight: 650; }}
    .meta {{ color: #5c5c5c; font-size: 0.9rem; margin-bottom: 22px; }}
    .turn {{ border: 1px solid #e0e0e0; border-radius: 10px; padding: 16px 18px; margin-bottom: 16px;
      background: #fafafa; }}
    .turn-head {{ margin-bottom: 10px; }}
    .turn-n {{ font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
      color: #666; }}
    .field {{ margin: 10px 0; }}
    .k {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;
      color: #555; display: block; margin-bottom: 4px; }}
    .v {{ font-size: 0.95rem; }}
    ul.tight {{ margin: 4px 0 0 1.1em; padding: 0; }}
    ul.tight li {{ margin: 3px 0; }}
    .chips {{ line-height: 1.9; }}
    .chip {{ display: inline-block; border-radius: 6px; padding: 2px 8px; margin: 2px 4px 2px 0;
      font-size: 0.8rem; vertical-align: middle; border: 1px solid #ccc; background: #fff; }}
    .chip code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.78rem; }}
    .chip-person {{ border-color: #2a6ebd; background: #eef5fc; }}
    .chip-claim {{ border-color: #b35a00; background: #fff5e6; }}
    .chip-policy {{ border-color: #1d7c4a; background: #e8f7ef; }}
    .chip-bank {{ border-color: #6b4fba; background: #f3effb; }}
    .chip-address {{ border-color: #555; background: #f0f0f0; }}
    .chip-business {{ border-color: #555; background: #f0f0f0; }}
    .chip-other {{ border-color: #999; background: #fff; }}
    .caveat {{ border-left: 3px solid #c45c00; padding-left: 12px; margin-top: 12px; background: #fff8f0;
      border-radius: 0 6px 6px 0; }}
    details.detail {{ margin-top: 12px; font-size: 0.88rem; }}
    details.detail summary {{ cursor: pointer; color: #444; }}
    pre.fulltext {{ white-space: pre-wrap; word-break: break-word; font-size: 0.82rem;
      background: #fff; border: 1px solid #e5e5e5; border-radius: 6px; padding: 10px; margin-top: 8px; }}
  </style>
</head>
<body>
  <h1>InvestigAI — session report</h1>
  <div class="meta">Generated {escape(generated)} UTC · {len(turns)} turn(s)</div>
  {rendered_turns or "<p>No session turns available.</p>"}
</body>
</html>
"""
