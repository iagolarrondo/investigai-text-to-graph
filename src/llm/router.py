"""
Intent router: natural language → investigation graph query.

Optional path for scripts or demos: classifies a question with **Anthropic Claude**
using ``SYSTEM_INTENT_ROUTER`` / ``FEW_SHOT_INTENT_EXAMPLES`` from ``prompts.py``,
then dispatches to concrete ``query_graph`` helpers. The main Streamlit app uses
the tool-planner orchestrator instead; this module does not require that flow.

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

from src.llm.prompts import FEW_SHOT_INTENT_EXAMPLES, SYSTEM_INTENT_ROUTER

IntentName = Literal[
    "claim_network",
    "claim_subgraph",
    "person_subgraph",
    "policy_network",
    "shared_bank",
    "people_clusters",
    "business_patterns",
    "unknown",
]

DEFAULT_CLAIM_NODE_ID = "claim_C9000000001"

_CLAIM_ID_PATTERN = re.compile(r"\b(?:claim_|Claim\|)[A-Za-z0-9|.+-]+", re.IGNORECASE)

VALID_INTENTS: frozenset[str] = frozenset(
    {
        "claim_network",
        "claim_subgraph",
        "person_subgraph",
        "policy_network",
        "shared_bank",
        "people_clusters",
        "business_patterns",
    }
)

# Stores raw debug info from the most recent routing call (for UI display)
last_routing_debug: dict = {}


@dataclass
class RouterDecision:
    intent: IntentName
    """Classifier output anchor (``anchor_node_id`` in JSON; legacy ``claim_node_id`` accepted)."""
    anchor_node_id: str | None
    """Resolved claim id for ``claim_network`` / ``claim_subgraph`` only."""
    claim_node_id: str | None
    source: Literal["llm"]
    reason: str
    matched_keywords: tuple[str, ...] = ()


def _extract_claim_node_id(text: str) -> str | None:
    m = _CLAIM_ID_PATTERN.search(text)
    return m.group(0) if m else None


def _json_anchor(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() in ("null", "none"):
            return None
        return s
    return str(value).strip() or None


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
            anchor_node_id=None,
            claim_node_id=None,
            source="llm",
            reason="ANTHROPIC_API_KEY is not set. Add it to your .env file.",
        )

    client = anthropic.Anthropic(api_key=api_key)
    router_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    messages = list(FEW_SHOT_INTENT_EXAMPLES) + [{"role": "user", "content": question}]

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
            model=router_model,
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
        intent_raw = parsed.get("intent", "unknown")
        intent = intent_raw if intent_raw in VALID_INTENTS else "unknown"

        anchor = _json_anchor(parsed.get("anchor_node_id")) or _json_anchor(parsed.get("claim_node_id"))
        reason = str(parsed.get("reason", "") or "")

        claim_node_id: str | None = None
        if intent in ("claim_network", "claim_subgraph"):
            if anchor and _CLAIM_ID_PATTERN.search(anchor):
                claim_node_id = anchor
            else:
                claim_node_id = _extract_claim_node_id(question) or DEFAULT_CLAIM_NODE_ID

        return RouterDecision(
            intent=intent,  # type: ignore[arg-type]
            anchor_node_id=anchor,
            claim_node_id=claim_node_id,
            source="llm",
            reason=reason,
        )

    except anthropic.AuthenticationError:
        return RouterDecision(
            intent="unknown",
            anchor_node_id=None,
            claim_node_id=None,
            source="llm",
            reason="Invalid ANTHROPIC_API_KEY — check your .env file.",
        )
    except Exception as exc:
        return RouterDecision(
            intent="unknown",
            anchor_node_id=None,
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

        if decision.intent == "person_subgraph":
            pid = decision.anchor_node_id
            if not pid:
                return {
                    "kind": "error",
                    "payload": None,
                    "decision": decision,
                    "error": "person_subgraph needs a Person anchor (classifier anchor_node_id or id in the question).",
                }
            return {"kind": "person_subgraph", "payload": qg.get_person_subgraph_summary(pid, max_depth=4), "decision": decision}

        if decision.intent == "policy_network":
            pol = decision.anchor_node_id
            if not pol:
                return {
                    "kind": "error",
                    "payload": None,
                    "decision": decision,
                    "error": "policy_network needs a Policy anchor (classifier anchor_node_id or id in the question).",
                }
            return {"kind": "policy_network", "payload": qg.get_policy_network(pol), "decision": decision}

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
    if kind in ("person_subgraph", "policy_network") and isinstance(payload, dict):
        return str(payload.get("explanation_plain") or payload.get("summary") or dec)
    if kind in ("shared_bank", "people_clusters", "business_patterns") and isinstance(payload, dict):
        return str(payload.get("explanation_plain") or dec)
    return str(kind)
