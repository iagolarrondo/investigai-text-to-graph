"""
**Ollama** (local) LLM: tool-planner loop and text-only judge/synthesis.

Requires `ollama` on PATH or Docker, a pulled model with **tool calling** (e.g. ``llama3.1``,
``qwen2.5``), and ``OLLAMA_HOST`` / ``OLLAMA_MODEL`` in the environment.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from ollama import Client


def graph_tools_for_ollama(graph_tool_specs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map internal tool specs to Ollama ``tools`` JSON (OpenAI-style function objects)."""
    out: list[dict[str, Any]] = []
    for spec in graph_tool_specs:
        schema = spec.get("input_schema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": (spec.get("description") or "")[:4096],
                    "parameters": schema,
                },
            }
        )
    return out


def _tool_call_name_args(tc: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(tc, dict):
        fn = tc.get("function") or {}
        name = str(fn.get("name") or "").strip()
        raw = fn.get("arguments")
    else:
        fn = tc.function
        name = str(getattr(fn, "name", None) or "").strip()
        raw = getattr(fn, "arguments", None)
    if isinstance(raw, dict):
        return name, dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return name, dict(json.loads(raw))
        except json.JSONDecodeError:
            return name, {}
    return name, {}


def ollama_generate_text(
    client: Client,
    *,
    model: str,
    system_instruction: str,
    user_text: str,
    num_predict: int = 8192,
    json_mode: bool = False,
) -> str:
    """Single-turn chat (judge / synthesis) without tools.

    When ``json_mode`` is True, requests Ollama ``format=\"json\"`` so the model emits valid JSON
    (helps coverage judge and synthesis stay parseable on smaller local models).
    """
    kwargs: dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_text},
        ],
        options={"num_predict": num_predict},
    )
    if json_mode:
        kwargs["format"] = "json"
    r = client.chat(**kwargs)
    return (r.message.content or "").strip()


def run_planner_phase_ollama(
    client: Client,
    messages: list[Any],
    out_steps: list[Any],
    *,
    model: str,
    graph_tool_specs: Sequence[dict[str, Any]],
    execute_tool: Callable[[str, dict[str, Any], bool], str],
    truncate_for_model: Callable[[str], str],
    append_tool_step: Callable[[str, dict[str, Any], str, int], None],
    planner_phase: int,
    max_rounds: int = 14,
    max_total_tool_steps: int | None = None,
) -> tuple[list[Any], int]:
    """
    Tool-use loop via Ollama (manual tool execution).

    ``messages`` must already include a ``system`` message and the opening ``user`` message.
    Assistant ``Message`` objects and plain ``tool`` dicts are appended in place.
    """
    tools = graph_tools_for_ollama(graph_tool_specs)
    api_calls = 0
    while api_calls < max_rounds:
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break
        try:
            r = client.chat(
                model=model,
                messages=messages,
                tools=tools,
                options={"num_predict": 8192},
            )
        except Exception as exc:
            raise RuntimeError(f"Ollama planner request failed: {exc}") from exc
        api_calls += 1
        msg = r.message
        messages.append(msg)
        tcs = getattr(msg, "tool_calls", None) or []
        if not tcs:
            break
        for tc in tcs:
            tname, tinp = _tool_call_name_args(tc)
            if not tname:
                continue
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
            messages.append({"role": "tool", "tool_name": tname, "content": body_api})
            if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
                break
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break
    return messages, api_calls
