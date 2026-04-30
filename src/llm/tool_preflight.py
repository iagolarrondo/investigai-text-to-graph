"""
**Preflight** LLM pass: whether current graph tools suffice (and how efficiently).

Runs before the main planner; optional extension authoring may follow.
"""

from __future__ import annotations

import json
from typing import Any

from src.llm.json_extract import extract_json_object
from src.llm.prompts import SYSTEM_TOOL_PREFLIGHT, SYSTEM_TOOL_PREFLIGHT_OLLAMA


def tool_catalog_json_from_graph_tools() -> str:
    """Compact JSON array of {name, description} for the preflight model."""
    from src.llm.tool_agent import GRAPH_TOOLS

    rows: list[dict[str, str]] = []
    for t in GRAPH_TOOLS:
        name = str(t.get("name", "")).strip()
        desc = str(t.get("description", ""))[:1200]
        if name:
            rows.append({"name": name, "description": desc})
    return json.dumps(rows, ensure_ascii=False)


def run_tool_preflight(
    backend: str,
    client: Any,
    model_name: str,
    question: str,
) -> dict[str, Any]:
    """
    Returns a dict with at least ``decision`` and ``rationale``; may include ``gap_summary``,
    ``efficiency_note``, ``recommended_plan``. On parse failure, returns a conservative default.
    """
    catalog = tool_catalog_json_from_graph_tools()
    user_blob = (
        f"USER_QUESTION:\n{question.strip()}\n\n"
        f"TOOL_CATALOG_JSON:\n{catalog}\n"
    )

    try:
        if backend == "ollama":
            from src.llm.local_ollama import ollama_generate_text

            raw = ollama_generate_text(
                client,
                model=model_name,
                system_instruction=SYSTEM_TOOL_PREFLIGHT_OLLAMA,
                user_text=user_blob,
                num_predict=2048,
                json_mode=True,
            )
        elif backend == "anthropic":
            from src.llm.anthropic_llm import anthropic_generate_text

            raw = anthropic_generate_text(
                client,
                model=model_name,
                system_instruction=SYSTEM_TOOL_PREFLIGHT,
                user_text=user_blob,
                max_tokens=2048,
            )
        else:
            from src.llm.gemini_llm import generate_text

            raw = generate_text(
                client,
                model=model_name,
                system_instruction=SYSTEM_TOOL_PREFLIGHT,
                user_text=user_blob,
                max_output_tokens=2048,
            )
    except Exception as exc:
        return {
            "decision": "sufficient",
            "rationale": f"Preflight call failed ({type(exc).__name__}); defaulting to sufficient.",
            "gap_summary": "",
            "efficiency_note": "",
            "recommended_plan": "",
            "preflight_error": str(exc),
        }

    data = extract_json_object(raw)
    if not isinstance(data, dict):
        return {
            "decision": "sufficient",
            "rationale": "Preflight returned invalid JSON; defaulting to sufficient.",
            "gap_summary": "",
            "efficiency_note": "",
            "recommended_plan": "",
            "preflight_raw_preview": (raw or "")[:1500],
        }

    decision = str(data.get("decision", "sufficient")).strip().lower().replace("-", "_")
    if decision not in ("sufficient", "insufficient", "sufficient_but_inefficient"):
        decision = "sufficient"

    return {
        "decision": decision,
        "rationale": str(data.get("rationale", "")).strip(),
        "gap_summary": str(data.get("gap_summary", "")).strip(),
        "efficiency_note": str(data.get("efficiency_note", "")).strip(),
        "recommended_plan": str(data.get("recommended_plan", "")).strip(),
    }
