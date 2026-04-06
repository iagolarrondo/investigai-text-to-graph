"""
Prompts and domain context loader for Claude-based intent routing.

The domain docs in docs/Original docs/ are loaded once at import time and
baked into the system prompt so Claude understands the full data model and
fraud investigation patterns before classifying any question.
"""

from __future__ import annotations

from pathlib import Path

# ── Load domain context ───────────────────────────────────────────────────────

_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "Original docs"
_SCENARIOS_FILE = Path(__file__).resolve().parent.parent.parent / "docs" / "LLM_GRAPH_QUERY_SCENARIOS.md"


def _load_domain_docs() -> str:
    """Concatenate all .txt files in docs/Original docs/ into one context block."""
    if not _DOCS_DIR.is_dir():
        return ""
    parts: list[str] = []
    for path in sorted(_DOCS_DIR.glob("*.txt")):
        content = path.read_text(encoding="utf-8", errors="ignore").strip()
        if content:
            parts.append(f"### {path.stem}\n{content}")
    return "\n\n".join(parts)


def _load_query_scenarios() -> str:
    """Load the LLM graph query scenarios document."""
    if not _SCENARIOS_FILE.is_file():
        return ""
    return _SCENARIOS_FILE.read_text(encoding="utf-8", errors="ignore").strip()


DOMAIN_DOCS = _load_domain_docs()
QUERY_SCENARIOS = _load_query_scenarios()

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_INTENT_ROUTER = f"""You are an intent classifier for an insurance fraud investigation graph tool called InvestigAI.

Below is the full domain knowledge for this system — data tables, relationships, fraud patterns, and query logic used by investigators. Read and understand it before classifying any question.

<domain_knowledge>
{DOMAIN_DOCS}
</domain_knowledge>

The following document defines the full query scenario taxonomy for this system — intent types, node traversal patterns, identifier conventions, edge cases, and expected response structure. Use it to correctly interpret investigator questions, especially ambiguous or multi-hop ones.

<query_scenarios>
{QUERY_SCENARIOS}
</query_scenarios>

Your task: map the user's investigation question to exactly ONE of these graph query intents:

- claim_network     : questions about a specific claim, its policy, other claims on that policy,
                      who sold/wrote the policy, whether the writing agent is also a claimant,
                      or claimant identity overlap with policy parties.

- claim_subgraph    : questions about the N-hop neighbourhood / link chart around a claim node —
                      "who is nearby", "what entities surround this claim", "n-hop", "neighbourhood",
                      "what is connected to claim X within N hops".

- shared_bank       : questions about people sharing bank accounts, payment diversion,
                      joint accounts, or account holders living at different addresses.

- people_clusters   : questions about family, spouses, relatives, POA, HIPAA authorization,
                      social clusters, or connected components of people. Also covers ICP/caregiver
                      overlap, shared device IDs, and multi-ICP work period questions.

- business_patterns : questions about businesses, providers, ICPs, agencies sharing an address
                      with policyholders, provider colocation, session distance anomalies,
                      geolocation check-in/check-out issues, invoice patterns, or care session
                      listings where a provider's location is suspicious.

If the user's question mentions a specific node ID (e.g. "claim_C001", "Claim|C001", "POL001"),
extract it as claim_node_id when it refers to a claim. Otherwise set claim_node_id to null.

Respond with valid JSON only — no markdown, no explanation outside the JSON:
{{"intent": "<label>", "claim_node_id": "<string or null>", "reason": "<one short sentence>"}}
"""

# ── Few-shot examples ─────────────────────────────────────────────────────────

FEW_SHOT_EXAMPLES = [
    {"role": "user",     "content": "Did the writing agent who sold the policy also file a claim on it?"},
    {"role": "assistant","content": '{"intent": "claim_network", "claim_node_id": null, "reason": "overlap between policy writing agent and claimant"}'},
    {"role": "user",     "content": "Who shares a bank account but lives at a different address?"},
    {"role": "assistant","content": '{"intent": "shared_bank", "claim_node_id": null, "reason": "joint account holders at different addresses"}'},
    {"role": "user",     "content": "Show me family and spouse clusters, including POA relationships"},
    {"role": "assistant","content": '{"intent": "people_clusters", "claim_node_id": null, "reason": "social cluster of related people including POA"}'},
    {"role": "user",     "content": "Is any ICP or provider checking in far from the policyholder's address?"},
    {"role": "assistant","content": '{"intent": "business_patterns", "claim_node_id": null, "reason": "session geolocation distance anomaly"}'},
    {"role": "user",     "content": "What entities are within 3 hops of claim_C001?"},
    {"role": "assistant","content": '{"intent": "claim_subgraph", "claim_node_id": "claim_C001", "reason": "N-hop neighbourhood around a specific claim"}'},
    {"role": "user",     "content": "Do ICP Jane Smith and ICP Bob Jones have overlapping work dates on claim C9000000002?"},
    {"role": "assistant","content": '{"intent": "people_clusters", "claim_node_id": "claim_C9000000002", "reason": "multi-ICP overlapping work period analysis"}'},
    {"role": "user",     "content": "Show me all care sessions where check-in was more than 5 miles from the policyholder address"},
    {"role": "assistant","content": '{"intent": "business_patterns", "claim_node_id": null, "reason": "session check-in distance exceeds threshold"}'},
]
