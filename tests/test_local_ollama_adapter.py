"""Unit tests for Ollama adapter (no running Ollama server required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.local_ollama import graph_tools_for_ollama  # noqa: E402
from src.llm.tool_agent import ANTHROPIC_MODEL, investigation_llm_backend  # noqa: E402


def test_graph_tools_for_ollama_maps_openai_style() -> None:
    specs = [
        {
            "name": "search_nodes",
            "description": "Find nodes",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }
    ]
    tools = graph_tools_for_ollama(specs)
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "search_nodes"
    assert tools[0]["function"]["parameters"]["type"] == "object"


def test_investigation_llm_backend_from_env(monkeypatch) -> None:
    monkeypatch.delenv("INVESTIGATION_LLM", raising=False)
    assert investigation_llm_backend() == "gemini"
    monkeypatch.setenv("INVESTIGATION_LLM", "ollama")
    assert investigation_llm_backend() == "ollama"
    monkeypatch.setenv("INVESTIGATION_LLM", "LOCAL")
    assert investigation_llm_backend() == "ollama"
    monkeypatch.setenv("INVESTIGATION_LLM", "anthropic")
    assert investigation_llm_backend() == "anthropic"
    monkeypatch.setenv("INVESTIGATION_LLM", "claude")
    assert investigation_llm_backend() == "anthropic"


def test_anthropic_model_default_is_non_empty() -> None:
    assert isinstance(ANTHROPIC_MODEL, str) and len(ANTHROPIC_MODEL) > 0
