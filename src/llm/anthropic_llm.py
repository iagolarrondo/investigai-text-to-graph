"""
**Anthropic (Claude)** Messages API: tool-planner loop and text-only judge/synthesis.

Uses the same full prompts as Gemini (``SYSTEM_TOOL_AGENT``, ``SYSTEM_COVERAGE_JUDGE``,
``SYSTEM_INVESTIGATION_SYNTHESIS_*`` — with embedded ``<graph_llm_summary>`` from ``graph_llm_summary.md``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from anthropic import Anthropic


def graph_tools_for_anthropic(graph_tool_specs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map internal tool specs to Anthropic ``tools`` (``input_schema`` = JSON Schema object)."""
    out: list[dict[str, Any]] = []
    for spec in graph_tool_specs:
        schema = spec.get("input_schema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        out.append(
            {
                "name": spec["name"],
                "description": (spec.get("description") or "")[:4096],
                "input_schema": schema,
            }
        )
    return out


def anthropic_generate_text(
    client: Anthropic,
    *,
    model: str,
    system_instruction: str,
    user_text: str,
    max_tokens: int = 8192,
) -> str:
    """Single-turn Messages call (coverage judge / synthesis)."""
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_instruction,
        messages=[{"role": "user", "content": user_text}],
    )
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def run_planner_phase_anthropic(
    client: Anthropic,
    messages: list[dict[str, Any]],
    out_steps: list[Any],
    *,
    model: str,
    graph_tool_specs: Sequence[dict[str, Any]],
    system_instruction: str,
    execute_tool: Callable[[str, dict[str, Any], bool], str],
    truncate_for_model: Callable[[str], str],
    append_tool_step: Callable[[str, dict[str, Any], str, int], None],
    planner_phase: int,
    max_rounds: int = 14,
    max_total_tool_steps: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Tool-use loop via Anthropic Messages API (manual tool execution).

    ``messages`` is a list of ``{"role": "user"|"assistant", "content": ...}`` turns using
    Anthropic content blocks. ``system_instruction`` is sent on every request (full planner prompt).
    """
    tools = graph_tools_for_anthropic(graph_tool_specs)
    api_calls = 0

    while api_calls < max_rounds:
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=8192,
                system=system_instruction,
                messages=messages,
                tools=tools,
            )
        except Exception as exc:
            raise RuntimeError(f"Anthropic planner request failed: {exc}") from exc

        api_calls += 1
        assistant_blocks: list[dict[str, Any]] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
            elif btype == "tool_use":
                raw_in = getattr(block, "input", None)
                tinp = dict(raw_in) if isinstance(raw_in, dict) else {}
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": tinp,
                    }
                )

        if not assistant_blocks:
            break

        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_uses = [b for b in assistant_blocks if b.get("type") == "tool_use"]
        if not tool_uses:
            break

        tool_result_blocks: list[dict[str, Any]] = []
        for b in tool_uses:
            tname = str(b.get("name") or "").strip()
            if not tname:
                continue
            tinp = b.get("input") if isinstance(b.get("input"), dict) else {}
            if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
                body_full = (
                    "STOPPED_TOOLING: Tool-step cap reached — this tool call was not executed "
                    f"(cap={max_total_tool_steps})."
                )
                body_api = truncate_for_model(body_full)
            else:
                body_full = execute_tool(tname, tinp, for_model=False)
                body_api = truncate_for_model(body_full)
                append_tool_step(tname, tinp, body_full, planner_phase)
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": b["id"],
                    "content": body_api,
                }
            )
            if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
                break

        if not tool_result_blocks:
            break
        messages.append({"role": "user", "content": tool_result_blocks})
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break

    return messages, api_calls
