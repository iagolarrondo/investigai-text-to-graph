"""Validate **read-only** Cypher before sending it to Aura (LLM-authored query path)."""

from __future__ import annotations

import json
import re

_FORBIDDEN = re.compile(
    r"\b("
    r"CREATE|MERGE|DELETE|REMOVE|DROP|INSERT|"
    r"DETACH\s+DELETE|LOAD\s+CSV|"
    r"GRANT|DENY|REVOKE|"
    r"FOREACH|CALL|"
    r"ALTER|DATABASE|INDEX|CONSTRAINT"
    r")\b",
    re.IGNORECASE,
)
_WRITE_SET = re.compile(r"\bSET\s+", re.IGNORECASE)


def extract_cypher_from_model_output(text: str) -> str:
    """Pull Cypher from a bare query or a ```cypher fenced block."""
    s = (text or "").strip()
    if not s:
        return ""
    m = re.search(r"```(?:cypher)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def validate_read_only_cypher(cypher: str) -> None:
    """Raise ``ValueError`` if the statement looks mutating or uses disallowed clauses."""
    s = (cypher or "").strip()
    if not s:
        raise ValueError("Empty Cypher statement.")
    core = s.rstrip().rstrip(";")
    if ";" in core:
        raise ValueError("Multiple Cypher statements are not allowed.")
    if _FORBIDDEN.search(s):
        raise ValueError("Cypher contains a forbidden keyword (writes, CALL, or DDL).")
    if _WRITE_SET.search(s):
        raise ValueError("SET (property writes) is not allowed in read-only mode.")


def parse_cypher_json_payload(text: str) -> tuple[str, dict[str, object]]:
    """
    Parse model output that must be JSON: ``{"cypher": "...", "params": {...}}``.

    Accepts optional markdown ```json fences. ``params`` defaults to ``{}`` if omitted.
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty model output for Cypher JSON.")
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model output is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("JSON root must be an object.")
    cy = obj.get("cypher")
    if not isinstance(cy, str) or not cy.strip():
        raise ValueError('JSON must contain a non-empty string "cypher".')
    params = obj.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError('"params" must be an object if present.')
    return cy.strip(), params


def parse_cypher_planner_json_payload(text: str) -> tuple[bool, str, dict[str, object], str]:
    """
    Parse **tool-free** planner output: ``{"done": <bool>, "cypher": "...", "params": {...}, "planner_note": "..."}``.

    When ``done`` is true, ``cypher`` may be omitted or empty (no query to run this turn).
    ``planner_note`` is optional in all cases.
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty model output for Cypher planner JSON.")
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model output is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("JSON root must be an object.")
    done = bool(obj.get("done"))
    note = str(obj.get("planner_note") or "").strip()
    if done:
        return True, "", {}, note
    cy = obj.get("cypher")
    if not isinstance(cy, str) or not cy.strip():
        raise ValueError('When "done" is false, JSON must contain a non-empty string "cypher".')
    params = obj.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError('"params" must be an object if present.')
    return False, cy.strip(), params, note
