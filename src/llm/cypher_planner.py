"""
Tool-free **Neo4j Cypher planner** for ``NEO4J_READ_MODE=llm_cypher``.

The investigation LLM emits read-only Cypher as JSON in a plain chat loop (no provider tool /
function calling). Steps are recorded as :class:`~src.llm.tool_agent.ToolAgentStep` with
``tool="__cypher__"`` so judge and synthesis stay compatible.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from src.graph_query.cypher_read_guard import (
    parse_cypher_planner_json_payload,
    validate_read_only_cypher,
)
from src.graph_query.extension_loader import read_registry_entries
from src.graph_store.neo4j_read_session import run_read_query
from src.llm.prompts import SYSTEM_CYPHER_PLANNER

CYPHER_PLANNER_STEP_TOOL = "__cypher__"

_ROW_CAP = 2000


def _extension_hints_appendix() -> str:
    rows: list[str] = []
    for e in read_registry_entries():
        if not e.get("active", True):
            continue
        name = str(e.get("name", "")).strip()
        if not name:
            continue
        desc = str(e.get("description", "")).strip()[:900]
        rows.append(f"- **{name}**: {desc}")
    if not rows:
        return ""
    return (
        "\n\n## Optional domain lenses (registry extensions — express in Cypher yourself)\n"
        "These are **hints** for common SIU patterns; there is no callable tool—mirror the intent in read-only Cypher.\n"
        + "\n".join(rows[:40])
    )


def full_planner_system_instruction() -> str:
    """Full system prompt for the Cypher-only planner (includes optional extension hints)."""
    return SYSTEM_CYPHER_PLANNER + _extension_hints_appendix()


def _rows_json_text(rows: list[dict[str, Any]]) -> str:
    if len(rows) > _ROW_CAP:
        rows = rows[:_ROW_CAP] + [{"_truncated": True, "_note": f"first {_ROW_CAP} row(s) only"}]
    return json.dumps(rows, indent=2, default=str)


def run_cypher_planner_phase_genai(
    client: Any,
    contents: list[Any],
    out_steps: list[Any],
    *,
    model: str,
    system_instruction: str,
    truncate_for_model: Callable[[str], str],
    append_tool_step: Callable[[str, dict[str, Any], str, int], None],
    planner_phase: int,
    max_rounds: int,
    max_total_tool_steps: int | None,
    progress_cb: callable | None,
) -> tuple[list[Any], int]:
    from google.genai import types

    from src.llm.gemini_llm import _candidate_text, _response_error_message

    def _emit(event_type: str, **data: Any) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb({"type": event_type, "planner_phase": planner_phase, **data})
        except Exception:
            return

    planner_cfg = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=8192,
    )
    api_calls = 0
    parse_fail_streak = 0

    while api_calls < max_rounds:
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=planner_cfg,
        )
        api_calls += 1
        err = _response_error_message(resp)
        if err:
            raise RuntimeError(err)
        text = _candidate_text(resp)
        if not text.strip():
            break
        contents.append(types.Content(role="model", parts=[types.Part(text=text)]))

        try:
            done, cypher, params, note = parse_cypher_planner_json_payload(text)
            parse_fail_streak = 0
        except ValueError as exc:
            parse_fail_streak += 1
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                "Your last reply was not valid JSON for this planner. "
                                f"Error: {exc}\n"
                                "Reply with **only** one JSON object: "
                                '{"done": false, "cypher": "...", "params": {}, "planner_note": ""} '
                                'or {"done": true, "planner_note": "..."}.'
                            )
                        )
                    ],
                )
            )
            if parse_fail_streak >= 4:
                break
            continue

        if done:
            break

        _emit("tool_start", tool=CYPHER_PLANNER_STEP_TOOL)
        try:
            validate_read_only_cypher(cypher)
            rows = run_read_query(cypher, params)
            body_full = _rows_json_text(rows)
        except Exception as exc:
            body_full = f"ERROR: {type(exc).__name__}: {exc}"
        _emit("tool_done", tool=CYPHER_PLANNER_STEP_TOOL)

        inp = {"cypher": cypher, "params": params, "planner_note": note}
        append_tool_step(CYPHER_PLANNER_STEP_TOOL, inp, body_full, planner_phase)

        body_api = truncate_for_model(body_full)
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=f"NEO4J_RESULT (truncated for context):\n{body_api}")],
            )
        )
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break

    return contents, api_calls


def run_cypher_planner_phase_anthropic(
    client: Any,
    messages: list[dict[str, Any]],
    out_steps: list[Any],
    *,
    model: str,
    system_instruction: str,
    truncate_for_model: Callable[[str], str],
    append_tool_step: Callable[[str, dict[str, Any], str, int], None],
    planner_phase: int,
    max_rounds: int,
    max_total_tool_steps: int | None,
    progress_cb: callable | None,
) -> tuple[list[dict[str, Any]], int]:
    def _emit(event_type: str, **data: Any) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb({"type": event_type, "planner_phase": planner_phase, **data})
        except Exception:
            return

    api_calls = 0
    parse_fail_streak = 0

    while api_calls < max_rounds:
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=8192,
                system=system_instruction,
                messages=messages,
            )
        except Exception as exc:
            raise RuntimeError(f"Anthropic Cypher planner request failed: {exc}") from exc
        api_calls += 1
        text_parts: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
        text = "\n".join(text_parts).strip()
        if not text:
            break
        messages.append({"role": "assistant", "content": text})

        try:
            done, cypher, params, note = parse_cypher_planner_json_payload(text)
            parse_fail_streak = 0
        except ValueError as exc:
            parse_fail_streak += 1
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your last reply was not valid JSON for this planner. "
                        f"Error: {exc}\n"
                        "Reply with **only** one JSON object as specified in the system prompt."
                    ),
                }
            )
            if parse_fail_streak >= 4:
                break
            continue

        if done:
            break

        _emit("tool_start", tool=CYPHER_PLANNER_STEP_TOOL)
        try:
            validate_read_only_cypher(cypher)
            rows = run_read_query(cypher, params)
            body_full = _rows_json_text(rows)
        except Exception as exc:
            body_full = f"ERROR: {type(exc).__name__}: {exc}"
        _emit("tool_done", tool=CYPHER_PLANNER_STEP_TOOL)

        inp = {"cypher": cypher, "params": params, "planner_note": note}
        append_tool_step(CYPHER_PLANNER_STEP_TOOL, inp, body_full, planner_phase)
        body_api = truncate_for_model(body_full)
        messages.append({"role": "user", "content": f"NEO4J_RESULT (truncated for context):\n{body_api}"})
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break

    return messages, api_calls


def run_cypher_planner_phase_ollama(
    client: Any,
    messages: list[Any],
    out_steps: list[Any],
    *,
    model: str,
    system_instruction: str,
    truncate_for_model: Callable[[str], str],
    append_tool_step: Callable[[str, dict[str, Any], str, int], None],
    planner_phase: int,
    max_rounds: int,
    max_total_tool_steps: int | None,
    progress_cb: callable | None,
) -> tuple[list[Any], int]:
    def _emit(event_type: str, **data: Any) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb({"type": event_type, "planner_phase": planner_phase, **data})
        except Exception:
            return

    if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        messages[0]["content"] = system_instruction

    api_calls = 0
    parse_fail_streak = 0

    while api_calls < max_rounds:
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break
        try:
            r = client.chat(
                model=model,
                messages=messages,
                options={"num_predict": 8192},
            )
        except Exception as exc:
            raise RuntimeError(f"Ollama Cypher planner request failed: {exc}") from exc
        api_calls += 1
        msg = r.message
        messages.append(msg)
        text = (msg.content or "").strip()
        if not text:
            break

        try:
            done, cypher, params, note = parse_cypher_planner_json_payload(text)
            parse_fail_streak = 0
        except ValueError as exc:
            parse_fail_streak += 1
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your last reply was not valid JSON for this planner. "
                        f"Error: {exc}\n"
                        "Reply with **only** one JSON object as specified in the system prompt."
                    ),
                }
            )
            if parse_fail_streak >= 4:
                break
            continue

        if done:
            break

        _emit("tool_start", tool=CYPHER_PLANNER_STEP_TOOL)
        try:
            validate_read_only_cypher(cypher)
            rows = run_read_query(cypher, params)
            body_full = _rows_json_text(rows)
        except Exception as exc:
            body_full = f"ERROR: {type(exc).__name__}: {exc}"
        _emit("tool_done", tool=CYPHER_PLANNER_STEP_TOOL)

        inp = {"cypher": cypher, "params": params, "planner_note": note}
        append_tool_step(CYPHER_PLANNER_STEP_TOOL, inp, body_full, planner_phase)
        body_api = truncate_for_model(body_full)
        messages.append({"role": "user", "content": f"NEO4J_RESULT (truncated for context):\n{body_api}"})
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break

    return messages, api_calls


def run_cypher_planner_phase(
    client: Any,
    contents: Any,
    out_steps: list[Any],
    *,
    planner_phase: int,
    max_rounds: int = 14,
    progress_cb: callable | None = None,
    max_total_tool_steps: int | None = None,
    truncate_for_model: Callable[[str], str],
    append_tool_step: Callable[[str, dict[str, Any], str, int], None],
) -> tuple[Any, int]:
    """Dispatch Cypher-only planner by ``INVESTIGATION_LLM`` backend."""
    from src.llm.tool_agent import (
        ANTHROPIC_MODEL,
        MODEL,
        OLLAMA_MODEL,
        investigation_llm_backend,
    )

    system_instruction = full_planner_system_instruction()
    backend = investigation_llm_backend()

    if backend == "ollama":
        return run_cypher_planner_phase_ollama(
            client,
            contents,
            out_steps,
            model=OLLAMA_MODEL,
            system_instruction=system_instruction,
            truncate_for_model=truncate_for_model,
            append_tool_step=append_tool_step,
            planner_phase=planner_phase,
            max_rounds=max_rounds,
            max_total_tool_steps=max_total_tool_steps,
            progress_cb=progress_cb,
        )
    if backend == "anthropic":
        return run_cypher_planner_phase_anthropic(
            client,
            contents,
            out_steps,
            model=ANTHROPIC_MODEL,
            system_instruction=system_instruction,
            truncate_for_model=truncate_for_model,
            append_tool_step=append_tool_step,
            planner_phase=planner_phase,
            max_rounds=max_rounds,
            max_total_tool_steps=max_total_tool_steps,
            progress_cb=progress_cb,
        )
    return run_cypher_planner_phase_genai(
        client,
        contents,
        out_steps,
        model=MODEL,
        system_instruction=system_instruction,
        truncate_for_model=truncate_for_model,
        append_tool_step=append_tool_step,
        planner_phase=planner_phase,
        max_rounds=max_rounds,
        max_total_tool_steps=max_total_tool_steps,
        progress_cb=progress_cb,
    )
