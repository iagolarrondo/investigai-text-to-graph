from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _render_turn(turn: dict[str, Any], idx: int) -> str:
    user_question = escape(str(turn.get("user_question", "")).strip())
    inv_question = escape(str(turn.get("investigation_question", "")).strip())
    answer = escape(str(turn.get("final_answer", "")).strip())
    focus = escape(str(turn.get("graph_focus_node_id") or ""))
    anchors = turn.get("anchors") or []
    notes = turn.get("reviewer_notes") or []

    inv_block = ""
    if inv_question and inv_question != user_question:
        inv_block = (
            "<div class='field'><span class='k'>Resolved investigation question:</span>"
            f"<div class='v'>{inv_question}</div></div>"
        )
    anchors_html = ""
    if anchors:
        chips = " ".join(f"<span class='chip'>{escape(str(a))}</span>" for a in anchors[:10])
        anchors_html = f"<div class='field'><span class='k'>Key entities:</span><div class='v'>{chips}</div></div>"
    notes_html = ""
    if notes:
        lis = "".join(f"<li>{escape(str(n))}</li>" for n in notes[:3])
        notes_html = f"<div class='field'><span class='k'>Reviewer notes:</span><ul>{lis}</ul></div>"
    focus_html = (
        f"<div class='field'><span class='k'>Graph focus:</span><span class='v mono'>{focus}</span></div>"
        if focus
        else ""
    )

    return (
        f"<section class='turn'><h3>Turn {idx}</h3>"
        f"<div class='field'><span class='k'>User question:</span><div class='v'>{user_question}</div></div>"
        f"{inv_block}"
        f"<div class='field'><span class='k'>Answer:</span><div class='v'>{answer}</div></div>"
        f"{focus_html}{anchors_html}{notes_html}</section>"
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
    body {{ font-family: Arial, sans-serif; margin: 24px; line-height: 1.35; color: #111; }}
    h1 {{ margin-bottom: 6px; }}
    .meta {{ color: #555; margin-bottom: 20px; }}
    .turn {{ border: 1px solid #ddd; border-radius: 8px; padding: 14px; margin-bottom: 14px; }}
    .field {{ margin: 8px 0; }}
    .k {{ font-weight: 600; display: inline-block; margin-right: 6px; }}
    .v {{ margin-top: 4px; }}
    .mono {{ font-family: ui-monospace, Menlo, monospace; }}
    .chip {{ display: inline-block; border: 1px solid #c8c8c8; border-radius: 12px; padding: 2px 8px; margin: 2px; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>InvestigAI Session Report</h1>
  <div class="meta">Generated: {escape(generated)} UTC<br/>Turns: {len(turns)}</div>
  {rendered_turns or "<p>No session turns available.</p>"}
</body>
</html>
"""

