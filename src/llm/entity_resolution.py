"""
Entity mention extraction (UI pre-step).

This is intentionally lightweight: given a user question, ask the configured backend
to return a small JSON array of {mention, node_type_hint} so the Streamlit UI can
search the graph deterministically and prompt the user to disambiguate.
"""

from __future__ import annotations

from typing import Any

import json

from src.llm.json_extract import strip_json_fence
from src.llm.prompts import SYSTEM_ENTITY_MENTION_EXTRACTOR
from src.llm.tool_agent import ANTHROPIC_MODEL, MODEL, OLLAMA_MODEL, investigation_llm_backend


def extract_entity_mentions_with_debug(question: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend = investigation_llm_backend()
    q = (question or "").strip()
    if not q:
        return [], {"backend": backend, "raw_preview": "", "error": "empty_question"}

    try:
        if backend == "ollama":
            from ollama import Client
            from src.llm.local_ollama import ollama_generate_text
            import os

            host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
            client: Any = Client(host=host)
            raw = ollama_generate_text(
                client,
                model=OLLAMA_MODEL,
                system_instruction=SYSTEM_ENTITY_MENTION_EXTRACTOR,
                user_text=f"QUESTION:\n{q}\n",
                num_predict=1024,
                json_mode=True,
            )
        elif backend == "anthropic":
            from anthropic import Anthropic
            from src.llm.anthropic_llm import anthropic_generate_text
            import os

            api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
            if not api_key:
                return [], {"backend": backend, "raw_preview": "", "error": "missing_anthropic_api_key"}
            client = Anthropic(api_key=api_key)
            raw = anthropic_generate_text(
                client,
                model=ANTHROPIC_MODEL,
                system_instruction=SYSTEM_ENTITY_MENTION_EXTRACTOR,
                user_text=f"QUESTION:\n{q}\n",
                max_tokens=1024,
            )
        else:
            from google import genai
            from src.llm.gemini_llm import generate_text
            import os

            api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
            if not api_key:
                return [], {"backend": backend, "raw_preview": "", "error": "missing_gemini_api_key"}
            client = genai.Client(api_key=api_key)
            raw = generate_text(
                client,
                model=MODEL,
                system_instruction=SYSTEM_ENTITY_MENTION_EXTRACTOR,
                user_text=f"QUESTION:\n{q}\n",
                max_output_tokens=1024,
            )
    except Exception as exc:
        return [], {"backend": backend, "raw_preview": "", "error": f"{type(exc).__name__}: {exc}"}

    # This extractor returns a JSON *array* (not an object), so parse it directly.
    raw_text = strip_json_fence(raw or "")
    dbg: dict[str, Any] = {"backend": backend, "raw_preview": raw_text[:800], "error": ""}
    try:
        data = json.loads(raw_text)
    except Exception as exc:
        dbg["error"] = f"json_parse_failed: {type(exc).__name__}: {exc}"
        data = None

    if isinstance(data, list):
        # Keep only items that look like {"mention": ..., "node_type_hint": ...}
        out: list[dict[str, Any]] = []
        for it in data[:5]:
            if not isinstance(it, dict):
                continue
            mention = str(it.get("mention", "")).strip()
            if not mention:
                continue
            nth = it.get("node_type_hint")
            if nth is not None:
                nth = str(nth).strip() or None
            out.append({"mention": mention, "node_type_hint": nth})
        return out, dbg
    if not dbg.get("error"):
        dbg["error"] = "not_a_json_array"
    return [], dbg


def extract_entity_mentions(question: str) -> list[dict[str, Any]]:
    mentions, _dbg = extract_entity_mentions_with_debug(question)
    return mentions

