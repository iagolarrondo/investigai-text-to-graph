"""
Investigation graph routing.

- **Auto** mode (Streamlit): ``route_question_auto`` calls **Claude** to classify the question
  into an investigation intent (JSON). Falls back to **keyword rules** if the API is
  unavailable or returns ``unknown``.
- **Manual** template selection: UI builds a :class:`RouterDecision` with ``source="rules"``.

``load_dotenv`` runs on import so ``ANTHROPIC_API_KEY`` is available.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

import anthropic

from src.llm.prompts import FEW_SHOT_INTENT_EXAMPLES, SYSTEM_INTENT_ROUTER

IntentName = Literal[
    "claim_network",
    "claim_subgraph",
    "shared_bank",
    "people_clusters",
    "business_patterns",
    "unknown",
]

# Must match a Claim node id in ``data/processed/nodes.csv`` (schema A: ``claim_*``, schema B: ``Claim|*``).
DEFAULT_CLAIM_NODE_ID = "Claim|C001"

_CLAIM_ID_PATTERN = re.compile(r"\b(?:claim_|Claim\|)[A-Za-z0-9|.+-]+", re.IGNORECASE)

VALID_INTENTS: set[str] = {
    "claim_network",
    "claim_subgraph",
    "shared_bank",
    "people_clusters",
    "business_patterns",
}

# Neighborhood / hop-style questions → claim_subgraph (rule fallback)
_SUBGRAPH_PATTERN = re.compile(
    r"(?:\b|^)(?:"
    r"hop|hops|neighborhood|neighbourhood|nearby|n-?hop|"
    r"subgraph|surround|entities around|link chart around|around this claim|"
    r"within\s+\d+\s*(?:hop|hops|step|steps)?"
    r")(?:\b|$)",
    re.IGNORECASE,
)


@dataclass
class RouterDecision:
    intent: IntentName
    claim_node_id: str | None
    source: Literal["llm", "rules"]
    reason: str
    matched_keywords: tuple[str, ...] = ()


def extract_claim_node_id(text: str) -> str | None:
    """Return a ``claim_*`` (or ``Claim|...``) token from ``text``, if any."""
    m = _CLAIM_ID_PATTERN.search(text)
    return m.group(0) if m else None


def claim_anchor_is_valid(claim_node_id: str) -> bool:
    """
    Return True if ``claim_node_id`` exists in the loaded graph and is a **Claim** node.

    Use this before claim-scoped queries so Person/Policy ids never reach
    ``get_claim_network`` / ``get_claim_subgraph_summary``.
    """
    from src.graph_query import query_graph as qg

    try:
        G = qg.get_graph()
    except RuntimeError:
        return False
    if claim_node_id not in G:
        return False
    return G.nodes[claim_node_id].get("node_type") == "Claim"


def route_question_llm(question: str) -> RouterDecision:
    """
    Send the question to Claude and parse JSON ``intent`` / ``claim_node_id`` / ``reason``.
    Returns ``unknown`` on missing API key, auth errors, or parse errors.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return RouterDecision(
            intent="unknown",
            claim_node_id=None,
            source="llm",
            reason="ANTHROPIC_API_KEY is not set. Add it to your .env file.",
        )

    client = anthropic.Anthropic(api_key=api_key)
    messages = list(FEW_SHOT_INTENT_EXAMPLES) + [{"role": "user", "content": question}]

    system = [
        {
            "type": "text",
            "text": SYSTEM_INTENT_ROUTER,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=256,
            system=system,
            messages=messages,
        )
        raw = response.content[0].text.strip()

        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        parsed = json.loads(raw)
        intent = parsed.get("intent", "unknown")
        if intent not in VALID_INTENTS:
            intent = "unknown"

        claim_node_id = parsed.get("claim_node_id") or extract_claim_node_id(question)
        reason = parsed.get("reason", "")

        return RouterDecision(
            intent=intent,  # type: ignore[arg-type]
            claim_node_id=claim_node_id if intent in ("claim_network", "claim_subgraph") else None,
            source="llm",
            reason=reason or "Classified by Claude.",
        )

    except anthropic.AuthenticationError:
        return RouterDecision(
            intent="unknown",
            claim_node_id=None,
            source="llm",
            reason="Invalid ANTHROPIC_API_KEY — check your .env file.",
        )
    except Exception as exc:
        return RouterDecision(
            intent="unknown",
            claim_node_id=None,
            source="llm",
            reason=f"Routing error: {exc}",
        )


def route_question_rules(question: str) -> RouterDecision:
    """
    Keyword / regex routing (no LLM). Used for fallback when Auto classification fails
    or returns unknown, and for tests.
    """
    q = (question or "").lower().strip()
    if not q:
        return RouterDecision(
            intent="unknown",
            claim_node_id=None,
            source="rules",
            reason="Empty question.",
            matched_keywords=(),
        )

    cid = extract_claim_node_id(question)
    matched: list[str] = []

    if _SUBGRAPH_PATTERN.search(q):
        matched.append("neighborhood/hop")
        return RouterDecision(
            intent="claim_subgraph",
            claim_node_id=cid,
            source="rules",
            reason="Matched neighborhood, hop-distance, or subgraph-style wording.",
            matched_keywords=tuple(matched),
        )

    bank_signals = ("bank", "account", "joint", "holder", "holders", "routing", "deposit")
    bank_context = any(s in q for s in bank_signals)
    sharing_signals = (
        "share",
        "shared",
        "two people",
        "multiple",
        "joint",
        "different address",
        "different addresses",
        "same account",
        "payment diversion",
        "multi-holder",
        "holders",
    )
    if bank_context and any(s in q for s in sharing_signals):
        matched.append("bank/account")
        return RouterDecision(
            intent="shared_bank",
            claim_node_id=None,
            source="rules",
            reason="Matched shared-bank or joint-account style wording.",
            matched_keywords=tuple(matched),
        )

    people_keys = (
        "family",
        "spouse",
        "relative",
        "cluster",
        "related",
        "marriage",
        "poa",
        "hipaa",
        "social",
        "sibling",
        "parent",
        "child",
    )
    if any(k in q for k in people_keys):
        matched.append("relationship")
        return RouterDecision(
            intent="people_clusters",
            claim_node_id=None,
            source="rules",
            reason="Matched family / relationship / cluster style wording.",
            matched_keywords=tuple(matched),
        )

    biz_keys = (
        "business",
        "provider",
        "agency",
        "colocation",
        "co-location",
        "same address",
        "icp",
        "home care",
        "facility",
        "geolocation",
        "check-in",
        "check in",
        "miles from",
    )
    if any(k in q for k in biz_keys):
        matched.append("business/location")
        return RouterDecision(
            intent="business_patterns",
            claim_node_id=None,
            source="rules",
            reason="Matched business, provider, or address-pattern wording.",
            matched_keywords=tuple(matched),
        )

    claim_keys = (
        "claim",
        "policy",
        "agent",
        "claimant",
        "writing",
        "wrote",
        "sold policy",
        "insured",
        "policyholder",
        "policy holder",
        "other claim",
        "same policy",
        "filed",
        "clm-",
    )
    if cid or any(k in q for k in claim_keys):
        matched.append("claim/policy")
        return RouterDecision(
            intent="claim_network",
            claim_node_id=cid,
            source="rules",
            reason="Matched claim, policy, or party wording (default claim-centric view).",
            matched_keywords=tuple(matched),
        )

    return RouterDecision(
        intent="unknown",
        claim_node_id=None,
        source="rules",
        reason="Could not match keywords. Pick an analysis type from the dropdown or mention claim/policy, bank, family, business, or hops/neighborhood.",
        matched_keywords=(),
    )


def route_question_auto(question: str) -> RouterDecision:
    """
    **Auto** routing: try LLM classification first; if ``unknown`` or API failure message
    suggests no usable intent, fall back to keyword rules (still returns a decision).
    """
    llm_dec = route_question_llm(question)

    if llm_dec.intent != "unknown":
        return llm_dec

    # Fallback: keyword rules when LLM could not classify
    fb = route_question_rules(question)
    if fb.intent != "unknown":
        return RouterDecision(
            intent=fb.intent,
            claim_node_id=fb.claim_node_id,
            source="rules",
            reason=f"LLM returned unknown ({llm_dec.reason}); fallback: {fb.reason}",
            matched_keywords=fb.matched_keywords,
        )

    return RouterDecision(
        intent="unknown",
        claim_node_id=None,
        source="llm",
        reason=llm_dec.reason or fb.reason,
        matched_keywords=(),
    )


def route_question(question: str, *, use_llm: bool = True) -> RouterDecision:
    """If ``use_llm``, use :func:`route_question_auto`; else :func:`route_question_rules`."""
    return route_question_auto(question) if use_llm else route_question_rules(question)


def dispatch_routed_query(decision: RouterDecision) -> dict[str, Any]:
    """Run the graph function matching ``decision.intent``."""
    from src.graph_query import query_graph as qg

    if decision.intent == "unknown":
        return {
            "kind": "unknown",
            "payload": None,
            "decision": decision,
            "error": decision.reason or "Could not map question to a query.",
        }

    try:
        if decision.intent == "claim_network":
            cid = decision.claim_node_id or DEFAULT_CLAIM_NODE_ID
            if not claim_anchor_is_valid(cid):
                return {
                    "kind": "error",
                    "payload": None,
                    "decision": decision,
                    "error": (
                        f"{cid!r} is not a Claim node in the loaded graph. "
                        "Use a claim id (e.g. Claim|C001, claim_C900…), not Person|… or Policy|…. "
                        "For person-centric questions, use **Planner** mode or templates that do not require a claim anchor."
                    ),
                }
            return {"kind": "claim_network", "payload": qg.get_claim_network(cid), "decision": decision}

        if decision.intent == "claim_subgraph":
            cid = decision.claim_node_id or DEFAULT_CLAIM_NODE_ID
            if not claim_anchor_is_valid(cid):
                return {
                    "kind": "error",
                    "payload": None,
                    "decision": decision,
                    "error": (
                        f"{cid!r} is not a Claim node in the loaded graph. "
                        "Use a claim id (e.g. Claim|C001, claim_C900…), not Person|… or Policy|…. "
                        "For person/policy relationship questions, use **Planner** mode instead of claim neighborhood."
                    ),
                }
            return {"kind": "claim_subgraph", "payload": qg.get_claim_subgraph_summary(cid, max_depth=4), "decision": decision}

        if decision.intent == "shared_bank":
            return {"kind": "shared_bank", "payload": qg.find_shared_bank_accounts(), "decision": decision}

        if decision.intent == "people_clusters":
            return {"kind": "people_clusters", "payload": qg.find_related_people_clusters(), "decision": decision}

        if decision.intent == "business_patterns":
            return {"kind": "business_patterns", "payload": qg.find_business_connection_patterns(), "decision": decision}

    except Exception as exc:
        return {"kind": "error", "payload": None, "decision": decision, "error": str(exc)}

    return {"kind": "error", "payload": None, "decision": decision, "error": f"Unhandled intent: {decision.intent}"}


def summary_for_display(result: dict[str, Any]) -> str:
    kind = result.get("kind")
    dec = result.get("decision")
    if result.get("error"):
        return f"[{kind}] {result['error']}"
    payload = result.get("payload")
    if kind == "claim_network" and isinstance(payload, dict):
        return payload.get("explanation_plain") or payload.get("summary", str(dec))
    if kind == "claim_subgraph" and isinstance(payload, dict):
        return str(payload.get("explanation_plain") or payload.get("summary") or dec)
    if kind in ("shared_bank", "people_clusters", "business_patterns") and isinstance(payload, dict):
        return str(payload.get("explanation_plain") or dec)
    return str(kind)
