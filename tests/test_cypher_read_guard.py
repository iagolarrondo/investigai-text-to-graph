"""Read-only Cypher guard helpers (no Neo4j)."""

from __future__ import annotations

import pytest

from src.graph_query.cypher_read_guard import (
    extract_cypher_from_model_output,
    parse_cypher_json_payload,
    parse_cypher_planner_json_payload,
    validate_read_only_cypher,
)


def test_validate_accepts_match() -> None:
    validate_read_only_cypher("MATCH (n:Entity) RETURN count(n) AS c LIMIT 1")


def test_validate_rejects_create() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        validate_read_only_cypher("CREATE (n:Entity)")


def test_validate_rejects_multi_statement() -> None:
    with pytest.raises(ValueError, match="Multiple"):
        validate_read_only_cypher("MATCH (n) RETURN n; MATCH (m) RETURN m")


def test_extract_fence() -> None:
    s = "Here:\n```cypher\nMATCH (n) RETURN n\n```"
    assert "MATCH (n) RETURN n" in extract_cypher_from_model_output(s)


def test_parse_cypher_json() -> None:
    cy, p = parse_cypher_json_payload('{"cypher": "MATCH (n:Entity) RETURN n LIMIT 1", "params": {}}')
    assert "MATCH" in cy
    assert p == {}


def test_parse_cypher_json_fenced() -> None:
    raw = '```json\n{"cypher": "RETURN 1 AS x", "params": {}}\n```'
    cy, p = parse_cypher_json_payload(raw)
    assert "RETURN" in cy
    assert p == {}


def test_parse_planner_json_done() -> None:
    done, cy, params, note = parse_cypher_planner_json_payload(
        '{"done": true, "planner_note": "ready for review"}'
    )
    assert done is True
    assert cy == ""
    assert params == {}
    assert note == "ready for review"


def test_parse_planner_json_cypher_round() -> None:
    done, cy, params, note = parse_cypher_planner_json_payload(
        '{"done": false, "cypher": "MATCH (n:Entity) RETURN count(n) AS c LIMIT 1", "params": {}}'
    )
    assert done is False
    assert "MATCH" in cy
    assert params == {}
    assert note == ""


def test_parse_planner_json_requires_cypher_when_not_done() -> None:
    with pytest.raises(ValueError, match="cypher"):
        parse_cypher_planner_json_payload('{"done": false, "params": {}}')
