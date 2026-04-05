"""
Intent router: natural language → investigation graph query.

**Prototype:** rule-based keyword scoring (no API calls).

**Later:** swap in ``route_question_llm()`` using ``prompts.py`` + your provider,
then keep the same ``RouterDecision`` + ``dispatch_routed_query()`` so Streamlit
or an API layer does not change.

---

Where this fits the **final product**:

1. **User** asks a question in plain English (chat UI, voice-to-text, etc.).
2. **Router** (this module) chooses *which* backend graph operation to run and
   *what arguments* it needs (e.g. ``claim_node_id``). This is a thin "intent"
   layer — not the full answer.
3. **Graph layer** (``query_graph``) runs deterministic NetworkX/pandas code on
   warehouse-backed exports.
4. **Presentation layer** shows tables/charts; optionally an **explainer LLM**
   summarizes results *after* the facts are known (safer than asking the LLM to
   invent graph paths).

Keeping routing separate from execution makes tests easy: unit-test rules and
LLM JSON parsing without loading the graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

# Lazy imports avoid circular deps; graph must be loaded before dispatch.
IntentName = Literal[
    "claim_network",
    "claim_subgraph",
    "shared_bank",
    "people_clusters",
    "business_patterns",
    "unknown",
]


@dataclass
class RouterDecision:
    """
    Result of routing: which query to run and optional arguments.

    ``source`` is ``"rules"`` today; later ``"llm"`` when you implement
    ``route_question_llm``.
    """

    intent: IntentName
    claim_node_id: str | None
    source: Literal["rules", "llm"]
    reason: str
    matched_keywords: tuple[str, ...] = ()


# Default claim used when the user asks about claims but does not name an id.
DEFAULT_CLAIM_NODE_ID = "claim_C9000000001"

# Regex for explicit claim ids in user text (matches our build_graph_files ids).
_CLAIM_ID_PATTERN = re.compile(r"\bclaim_[A-Za-z0-9]+\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _extract_claim_node_id(text: str) -> str | None:
    m = _CLAIM_ID_PATTERN.search(text)
    if not m:
        return None
    return m.group(0)


# Keywords per intent (simple overlap scoring).
_RULE_KEYWORDS: dict[IntentName, frozenset[str]] = {
    "claim_network": frozenset(
        {
            "claim",
            "claims",
            "claimant",
            "policy",
            "policies",
            "agent",
            "writing",
            "sold",
            "underwriting",
            "maria",
            "c9000000002",
            "c9000000001",
            "c9000000005",
            "00240",
            "pat kim",
            "overlap",
            "same policy",
        }
    ),
    "claim_subgraph": frozenset(
        {
            "neighborhood",
            "neighbourhood",
            "n-hop",
            "nhop",
            "multi-hop",
            "multihop",
            "ego",
            "surrounding",
            "nearby",
            "within 2",
            "2 steps",
            "two steps",
            "local subgraph",
            "entities within",
        }
    ),
    "shared_bank": frozenset(
        {
            "bank",
            "account",
            "routing",
            "holder",
            "holders",
            "shared",
            "joint",
            "payment",
            "diversion",
            "mule",
            "different address",
            "addresses",
            "household",
        }
    ),
    "people_clusters": frozenset(
        {
            "family",
            "relative",
            "relatives",
            "spouse",
            "cousin",
            "sister",
            "brother",
            "kin",
            "cluster",
            "social",
            "related",
            "relationship",
        }
    ),
    "business_patterns": frozenset(
        {
            "business",
            "businesses",
            "provider",
            "agency",
            "hhca",
            "nursing",
            "colocation",
            "colocate",
            "same address",
            "location",
            "resolve care",
            "apex",
            "billing",
            "lynn",
            "commerce",
        }
    ),
    "unknown": frozenset(),
}


def route_question_rules(question: str) -> RouterDecision:
    """
    Score each intent by counting keyword hits in ``question`` (after lowercasing).

    Tie-break order: ``claim_subgraph`` is listed **before** ``claim_network`` so that
    questions that mention both a claim id and **neighborhood / hop** vocabulary prefer
    the N-hop slice; otherwise scores decide as usual.

    For ``claim_network`` and ``claim_subgraph``, if no ``claim_...`` token appears,
    uses ``DEFAULT_CLAIM_NODE_ID`` (or a demo override for Pat Kim / C9000000005).
    """
    q = _normalize(question)
    scores: dict[IntentName, int] = {k: 0 for k in _RULE_KEYWORDS if k != "unknown"}
    matched: dict[IntentName, list[str]] = {k: [] for k in scores}

    for intent, words in _RULE_KEYWORDS.items():
        if intent == "unknown":
            continue
        for w in words:
            if w in q:
                scores[intent] += 1
                matched[intent].append(w)

    # Max score, then first match in tie_order (claim_subgraph before claim_network)
    tie_order: list[IntentName] = [
        "claim_subgraph",
        "claim_network",
        "shared_bank",
        "people_clusters",
        "business_patterns",
    ]
    best_score = max(scores.values())
    best: IntentName = "unknown"
    if best_score > 0:
        for name in tie_order:
            if scores[name] == best_score:
                best = name
                break

    if best_score == 0:
        return RouterDecision(
            intent="unknown",
            claim_node_id=None,
            source="rules",
            reason="No keywords matched; try rephrasing or use an LLM router.",
            matched_keywords=(),
        )

    claim_id = _extract_claim_node_id(question)
    if best in ("claim_network", "claim_subgraph"):
        if claim_id is None:
            # Demo seed: Pat Kim claim (no need to type claim_… if the question names them)
            if re.search(r"\bc9000000005\b", q) or "pat kim" in q:
                claim_id = "claim_C9000000005"
            else:
                claim_id = DEFAULT_CLAIM_NODE_ID
        reason = f"Keyword match (score={best_score}) → {best}; claim_id={claim_id}"
    else:
        reason = f"Keyword match (score={best_score}) → {best}"

    return RouterDecision(
        intent=best,
        claim_node_id=claim_id if best in ("claim_network", "claim_subgraph") else None,
        source="rules",
        reason=reason,
        matched_keywords=tuple(sorted(set(matched[best]))),
    )


def route_question_llm(question: str) -> RouterDecision:
    """
    **Placeholder** for LLM-based routing.

    Intended steps when you implement:
    1. Import ``SYSTEM_INTENT_ROUTER``, ``USER_QUESTION_TEMPLATE``, optional
       ``FEW_SHOT_EXAMPLES`` from ``src.llm.prompts``.
    2. Call your API (OpenAI, Azure, etc.) with JSON response format or
       ``response_format={"type": "json_object"}`` where supported.
    3. Parse JSON into ``intent``, ``claim_node_id``, ``reason``.
    4. Validate ``intent`` is one of the four known labels (or map synonyms).
    5. Return ``RouterDecision(..., source="llm", ...)``.

    Raise ``NotImplementedError`` until wired — keeps imports cheap for demos.
    """
    raise NotImplementedError(
        "LLM router not implemented. Use route_question_rules(question) or "
        "wire prompts.SYSTEM_INTENT_ROUTER + your API here."
    )


def route_question(question: str, *, use_llm: bool = False) -> RouterDecision:
    """
    Single entry point: set ``use_llm=True`` when ``route_question_llm`` is ready.
    """
    if use_llm:
        return route_question_llm(question)
    return route_question_rules(question)


def dispatch_routed_query(decision: RouterDecision) -> dict[str, Any]:
    """
    Run the graph function that matches ``decision.intent``.

    **Requires** ``query_graph.load_graph()`` to have been called already.

    Returns a small dict with keys:
    - ``kind`` — same as intent (or "error")
    - ``payload`` — return value from the graph function (dict of DataFrames, etc.)
    - ``decision`` — the decision echoed for UI display
    """
    from src.graph_query import query_graph as qg

    if decision.intent == "unknown":
        return {
            "kind": "unknown",
            "payload": None,
            "decision": decision,
            "error": "Could not map question to a query.",
        }

    try:
        if decision.intent == "claim_network":
            cid = decision.claim_node_id or DEFAULT_CLAIM_NODE_ID
            payload = qg.get_claim_network(cid)
            return {"kind": "claim_network", "payload": payload, "decision": decision}

        if decision.intent == "claim_subgraph":
            cid = decision.claim_node_id or DEFAULT_CLAIM_NODE_ID
            # Depth 4 on the synthetic seed reaches billing business via shared address
            # (API default remains 2 for conservative slices).
            payload = qg.get_claim_subgraph_summary(cid, max_depth=4)
            return {"kind": "claim_subgraph", "payload": payload, "decision": decision}

        if decision.intent == "shared_bank":
            return {
                "kind": "shared_bank",
                "payload": qg.find_shared_bank_accounts(),
                "decision": decision,
            }

        if decision.intent == "people_clusters":
            return {
                "kind": "people_clusters",
                "payload": qg.find_related_people_clusters(),
                "decision": decision,
            }

        if decision.intent == "business_patterns":
            return {
                "kind": "business_patterns",
                "payload": qg.find_business_connection_patterns(),
                "decision": decision,
            }
    except Exception as e:  # noqa: BLE001 — educational: show message upstream
        return {
            "kind": "error",
            "payload": None,
            "decision": decision,
            "error": str(e),
        }

    return {
        "kind": "error",
        "payload": None,
        "decision": decision,
        "error": f"Unhandled intent: {decision.intent}",
    }


def summary_for_display(result: dict[str, Any]) -> str:
    """One-line text for Streamlit / CLI when payload is nested."""
    kind = result.get("kind")
    dec = result.get("decision")
    if result.get("error"):
        return f"[{kind}] {result['error']}"
    payload = result.get("payload")
    if kind == "claim_network" and isinstance(payload, dict):
        return payload.get("explanation_plain") or payload.get("summary", str(dec))
    if kind == "claim_subgraph" and isinstance(payload, dict):
        return str(payload.get("explanation_plain") or payload.get("summary") or dec)
    if kind in ("shared_bank", "people_clusters", "business_patterns") and isinstance(
        payload, dict
    ):
        return str(payload.get("explanation_plain") or dec)
    if dec and hasattr(dec, "reason"):
        return f"[{kind}] {dec.reason}"
    return str(kind)
