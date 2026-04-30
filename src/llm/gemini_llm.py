"""
Gemini (**Google Gen AI** SDK) helpers: tool-planner loop, text-only judge/synthesis calls.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from google import genai
from google.genai import types


def graph_tools_for_gemini(graph_tool_specs: Sequence[dict[str, Any]]) -> types.Tool:
    """Map Anthropic-style tool specs to Gemini ``FunctionDeclaration``."""
    declarations: list[types.FunctionDeclaration] = []
    for spec in graph_tool_specs:
        schema = spec.get("input_schema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        declarations.append(
            types.FunctionDeclaration(
                name=spec["name"],
                description=(spec.get("description") or "")[:4096],
                parameters_json_schema=schema,
            )
        )
    return types.Tool(function_declarations=declarations)


def _response_error_message(resp: types.GenerateContentResponse) -> str | None:
    if resp.prompt_feedback and getattr(resp.prompt_feedback, "block_reason", None):
        return f"Prompt blocked: {resp.prompt_feedback.block_reason}"
    if not resp.candidates:
        return "Model returned no candidates (empty or blocked response)."
    fr = resp.candidates[0].finish_reason
    if fr and "SAFETY" in str(fr).upper():
        return f"Candidate stopped: finish_reason={fr}"
    return None


def _candidate_text(resp: types.GenerateContentResponse) -> str:
    c0 = resp.candidates[0] if resp.candidates else None
    if not c0 or not c0.content or not c0.content.parts:
        return ""
    chunks: list[str] = []
    for p in c0.content.parts:
        if p.text and not (getattr(p, "thought", False)):
            chunks.append(p.text)
    return "\n".join(chunks).strip()


def generate_text(
    client: genai.Client,
    *,
    model: str,
    system_instruction: str,
    user_text: str,
    max_output_tokens: int,
) -> str:
    """Single-turn text generation (judge / synthesis)."""
    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[types.Part(text=user_text)],
            )
        ],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
        ),
    )
    err = _response_error_message(resp)
    if err:
        raise RuntimeError(err)
    return _candidate_text(resp)


def run_planner_phase_genai(
    client: genai.Client,
    contents: list[types.Content],
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
) -> tuple[list[types.Content], int]:
    """
    Tool-use loop using Gemini function calling (manual execution; automatic calling disabled).

    ``execute_tool(name, inp, for_model) -> str`` matches :func:`src.llm.tool_agent.execute_graph_tool`.
    ``append_tool_step(name, inp, body_full, planner_phase)`` records a :class:`~src.llm.tool_agent.ToolAgentStep`.
    """
    tool = graph_tools_for_gemini(graph_tool_specs)
    planner_cfg = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[tool],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.AUTO,
            )
        ),
        max_output_tokens=8192,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    api_calls = 0
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

        cand = resp.candidates[0]
        model_content = cand.content
        if not model_content or not model_content.parts:
            break

        contents.append(model_content)

        calls: list[types.FunctionCall] = []
        for p in model_content.parts:
            if p.function_call:
                calls.append(p.function_call)

        if not calls:
            break

        fr_parts: list[types.Part] = []
        for fc in calls:
            tname = (fc.name or "").strip()
            raw_args = fc.args
            tinp = dict(raw_args) if isinstance(raw_args, dict) else (dict(raw_args) if raw_args else {})
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
            fr_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=tname,
                        id=fc.id,
                        response={"result": body_api},
                    )
                )
            )
            if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
                break

        contents.append(types.Content(role="user", parts=fr_parts))
        if max_total_tool_steps is not None and len(out_steps) >= max_total_tool_steps:
            break

    return contents, api_calls
