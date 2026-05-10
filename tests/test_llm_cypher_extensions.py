"""Extension tools + LLM Cypher path (no live LLM / Neo4j)."""

from __future__ import annotations

import pytest


def test_execute_extension_via_llm_cypher_unknown_tool() -> None:
    from src.llm.cypher_tool_execution import execute_extension_via_llm_cypher

    out = execute_extension_via_llm_cypher("tool_that_is_not_in_registry_xxx", {})
    assert out.startswith("ERROR:")
    assert "registry" in out.lower()
