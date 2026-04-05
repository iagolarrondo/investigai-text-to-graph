"""
Prompt text and templates for **future** LLM-based intent routing.

The prototype uses a **rule-based** router in ``router.py`` so you can run the
pipeline without API keys. When you add an LLM:

1. Build a short system + user message from the constants below (or revise them).
2. Ask the model to output **structured JSON** matching ``RouterDecision`` fields
   (see ``router.py``): ``intent``, optional ``claim_node_id``, short ``reason``.
3. Parse JSON and validate against allowed ``intent`` values.

---

How this fits the **final product** (high level):

- **InvestigAI** front end (chat or search box) sends the user's natural language
  question to a **router** stage.
- That stage either uses **rules** (cheap, predictable demos) or an **LLM**
  (flexible wording, multi-intent hints) to pick a **structured intent**.
- A **dispatcher** then calls the right graph function(s), optionally composes
  follow-up queries, and passes tabular results to **explanation / reporting**
  (another LLM call or templates).

Keep prompts **small** and **schema-focused** so the model does classification,
not free-form investigation (which belongs after you have query results).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Future LLM: system message (classification only)
# ---------------------------------------------------------------------------
# Tweak tool names / intents here when you add new graph queries.

SYSTEM_INTENT_ROUTER = """You are a classifier for an insurance investigation graph prototype.

Map the user's question to exactly ONE intent label from this list:
- claim_network — questions about a specific claim, its policy, other claims on that policy, people tied to the policy (insured, agent), or claimant identity.
- shared_bank — questions about people sharing bank accounts, payment diversion, different addresses for same account.
- people_clusters — questions about family, spouses, relatives, or social clusters in the graph.
- business_patterns — questions about businesses, providers, agencies, or sharing an address with people.

Also extract a claim node id if the user gives one like claim_C9000000002 (optional).

Respond with JSON only, no markdown:
{"intent": "<label>", "claim_node_id": "<string or null>", "reason": "<one short sentence>"}
"""

# ---------------------------------------------------------------------------
# Future LLM: user message template
# ---------------------------------------------------------------------------

USER_QUESTION_TEMPLATE = """User question:
{question}
"""

# ---------------------------------------------------------------------------
# Few-shot examples (optional — enable when you wire the API)
# ---------------------------------------------------------------------------
# Paste into the system message or as separate assistant/user turns.

FEW_SHOT_EXAMPLES = """
Examples:
Q: "Did Maria sell the policy she claimed on?"
A: {"intent": "claim_network", "claim_node_id": "claim_C9000000002", "reason": "claim and agent overlap"}

Q: "Who shares a bank account but lives somewhere else?"
A: {"intent": "shared_bank", "claim_node_id": null, "reason": "shared account and addresses"}

Q: "Show me family clusters"
A: {"intent": "people_clusters", "claim_node_id": null, "reason": "family grouping"}

Q: "Is the home health business at the same address as claimants?"
A: {"intent": "business_patterns", "claim_node_id": null, "reason": "business colocation"}
"""
