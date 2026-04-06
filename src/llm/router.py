"""
Intent router: natural language → investigation graph query.

Uses Claude (claude-opus-4-6) via the Anthropic API to classify the user's
question into one of five investigation intents, then dispatches to the
matching graph query function.

API key setup
─────────────
Set your key in the project .env file (recommended):

    ANTHROPIC_API_KEY=sk-ant-...

Or export it in your shell before running:

    export ANTHROPIC_API_KEY=sk-ant-...

The .env file is loaded automatically when this module is imported.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# Load .env from project root so ANTHROPIC_API_KEY is available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on shell env

import anthropic

from src.llm.prompts import FEW_SHOT_EXAMPLES, SYSTEM_INTENT_ROUTER

IntentName = Literal[
    "claim_network",
    "claim_subgraph",
    "shared_bank",
    "people_clusters",
    "business_patterns",
    "unknown",
]

DEFAULT_CLAIM_NODE_ID = "claim_C9000000001"

_CLAIM_ID_PATTERN = re.compile(r"\b(?:claim_|Claim\|)[A-Za-z0-9|.+-]+", re.IGNORECASE)

VALID_INTENTS: set[str] = {
    "claim_network",
    "claim_subgraph",
    "shared_bank",
    "people_clusters",
    "business_patterns",
}

# Stores raw debug info from the most recent routing call (for UI display)
last_routing_debug: dict = {}


@dataclass
class RouterDecision:
    intent: IntentName
    claim_node_id: str | None
    source: Literal["llm"]
    reason: str
    matched_keywords: tuple[str, ...] = ()


def _extract_claim_node_id(text: str) -> str | None:
    m = _CLAIM_ID_PATTERN.search(text)
    return m.group(0) if m else None


def route_question_rules(question: str) -> RouterDecision:
    """Thin wrapper — all routing now goes through the LLM."""
    return route_question_llm(question)


def route_question_llm(question: str) -> RouterDecision:
    """
    Send the question to Claude and parse the returned JSON intent.
    Falls back to intent='unknown' on any API or parse error.
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

    messages = list(FEW_SHOT_EXAMPLES) + [{"role": "user", "content": question}]

    # System prompt is sent as a cacheable block — the domain docs (~40KB) are
    # static, so after the first call they are served from cache at ~10% cost.
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

        last_routing_debug["system_prompt"] = SYSTEM_INTENT_ROUTER
        last_routing_debug["messages"] = messages
        last_routing_debug["raw_response"] = raw

        # Strip markdown fences if the model wraps with ```json ... ```
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        parsed = json.loads(raw)
        intent = parsed.get("intent", "unknown")
        if intent not in VALID_INTENTS:
            intent = "unknown"

        claim_node_id = parsed.get("claim_node_id") or _extract_claim_node_id(question)
        reason = parsed.get("reason", "")

        return RouterDecision(
            intent=intent,
            claim_node_id=claim_node_id if intent in ("claim_network", "claim_subgraph") else None,
            source="llm",
            reason=reason,
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


def route_question(question: str, *, use_llm: bool = True) -> RouterDecision:
    return route_question_llm(question)


def dispatch_routed_query(decision: RouterDecision) -> dict[str, Any]:
    """Run the graph function matching decision.intent."""
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
            return {"kind": "claim_network", "payload": qg.get_claim_network(cid), "decision": decision}

        if decision.intent == "claim_subgraph":
            cid = decision.claim_node_id or DEFAULT_CLAIM_NODE_ID
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
