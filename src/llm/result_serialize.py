"""Compact text serialization of graph query payloads for LLM context."""

from __future__ import annotations

import pandas as pd


def payload_to_text(kind: str, payload: object) -> str:
    """Serialise query results to a compact text block for the LLM."""
    lines: list[str] = []

    def _df_summary(label: str, df: pd.DataFrame) -> None:
        if not isinstance(df, pd.DataFrame) or df.empty:
            lines.append(f"{label}: (empty)")
            return
        lines.append(f"{label} ({len(df)} row(s)):")
        lines.append(df.to_string(index=False, max_rows=30))

    if kind == "claim_network" and isinstance(payload, dict):
        for key in (
            "claim",
            "linked_policies",
            "other_claims_on_policy",
            "people_linked_to_claim",
            "people_linked_to_policy",
            "claimant_person_match",
        ):
            _df_summary(key.replace("_", " ").title(), payload.get(key))
    elif kind in ("claim_subgraph", "person_subgraph") and isinstance(payload, dict):
        tc = payload.get("type_counts")
        if isinstance(tc, pd.DataFrame):
            lines.append("Type counts:\n" + tc.to_string(index=False))
        _df_summary("Nodes", payload.get("nodes"))
        _df_summary("Edges", payload.get("edges"))
    elif kind == "policy_network" and isinstance(payload, dict):
        for key in ("policy", "people_on_policy", "claims_on_policy"):
            _df_summary(key.replace("_", " ").title(), payload.get(key))
    elif isinstance(payload, dict) and "table" in payload:
        _df_summary("Results", payload.get("table"))
    elif kind == "person_policies" and isinstance(payload, dict):
        _df_summary("Policies", payload.get("policies"))
    elif kind == "search_nodes" and isinstance(payload, dict):
        _df_summary("Matches", payload.get("matches"))
    elif isinstance(payload, pd.DataFrame):
        _df_summary("Results", payload)

    return "\n".join(lines) if lines else "(no data)"


def investigation_payload_to_text(kind: str, payload: object) -> str:
    """
    Serialize any investigation dict from ``query_graph`` using the right layout.

    ``kind`` is a short label such as ``claim_network``, ``claim_subgraph``, ``person_subgraph``,
    ``policy_network``, ``person_policies``, ``search_nodes``.
    """
    return payload_to_text(kind, payload)
