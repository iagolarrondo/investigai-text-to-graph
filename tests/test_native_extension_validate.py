"""Static validation for native extension modules (no Neo4j)."""

from __future__ import annotations

from src.llm.native_extension_author import _validate_native_extension_source


def test_validate_accepts_minimal_native_module() -> None:
    src = '''
from __future__ import annotations

import json
from typing import Any

from src.graph_store.neo4j_read_session import run_read_query as rq


def run_native(tool_input: dict[str, Any]) -> str:
    rows = rq("MATCH (n:Entity) RETURN count(n) AS c LIMIT 1", {})
    return json.dumps(rows, default=str)
'''
    assert _validate_native_extension_source(src) is None


def test_validate_rejects_get_graph() -> None:
    src = """
from __future__ import annotations
import json
from typing import Any
from src.graph_store.neo4j_read_session import run_read_query as rq

def run_native(tool_input: dict[str, Any]) -> str:
    x = get_graph
    return json.dumps([])
"""
    err = _validate_native_extension_source(src)
    assert err and "get_graph" in err
