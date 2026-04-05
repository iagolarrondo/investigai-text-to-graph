# Team briefing — graph investigation PoC (pre-meeting)

**Purpose:** Align before the next sync on what exists, what it proves, and what we still need to decide. This is a **local prototype** with **synthetic data**; it is not a production system.

---

## 1. What we have already built

- **Synthetic seed dataset** (`data/interim/poc_v1_seed/`) — small CSV extracts (people, policies, claims, banks, addresses, businesses, crosswalks) that tell a coherent demo story.
- **Graph build script** — reads the seed and writes **`nodes.csv`** and **`edges.csv`** under `data/processed/`, with basic validation (e.g. edges point to existing nodes).
- **Query module** — loads the graph in memory and runs investigation-style queries (claim neighborhood, shared banks, family-style clusters, business–address overlap). Results include **tables**, a **short explanation**, and **supporting graph links** for investigator-facing demos.
- **Streamlit app** — predefined questions, free-text input, **rule-based** question routing (no LLM API required for the current path), and a **small subgraph** view after each answer.
- **Light quality checks** — pytest smoke tests on the processed CSVs; README and supporting docs (`demo_cases`, `technical_flow`, `roadmap`) for onboarding and demos.

---

## 2. What the current prototype demonstrates

- **End-to-end story:** staged tabular inputs → graph export → repeatable queries → UI a non-developer can run on a laptop.
- **Investigator-friendly output:** not just raw tables — brief “why this showed up” copy and explicit relationships/ids to support narrative in a fraud review **conversation** (still demo-grade wording).
- **Named demo scenarios** (e.g. agent/claimant overlap, shared bank with different addresses, family ties, business colocated with people) documented for presenters — see `docs/demo_cases.md`.

It **does not** demonstrate enterprise scale, live feeds, or formal model accuracy against real cases.

---

## 3. What is still synthetic or simplified

- **All seed data is fictional** — safe for screenshots and external demos; **no** real customer or production fields.
- **Graph lives as two CSV files** — not a database; no concurrent users, no incremental load, no enterprise backup or access control.
- **Natural language is rule-matched** — keyword/intent style routing, not a trained or hosted NLU/LLM product.
- **Visualization is minimal** — useful for PoC, not a full graph analytics product.
- **Scope of queries is narrow** — a handful of patterns we chose for the story; many real SIU questions are not implemented.

Being clear about this in meetings avoids confusion with “what ships to production.”

---

## 4. Key design decisions already made

- **Property graph model** — nodes typed (Person, Claim, Policy, etc.) and edges typed (e.g. `IS_CLAIM_AGAINST_POLICY`, `HOLD_BY`, `LOCATED_IN`); properties carried as JSON on nodes/edges in CSV.
- **Stable synthetic ids** in the export (`person_5001`, `claim_C9000000002`, …) so queries, tests, and UI subgraph scraping stay consistent.
- **Build-time integrity** — prefer skipping bad edges over emitting orphans where the builder enforces endpoint existence.
- **Demo-first UX** — Streamlit for speed; investigator copy and subgraph bundled with each query result.
- **No external AI dependency in v1 routing** — keeps setup simple and avoids API keys for the default path.

---

## 5. Open decisions for the team (discussion topics)

- **Target user and setting** — lab demo vs. pilot with a specific SIU workflow; what “success” looks like in the next milestone.
- **Data path** — whether the next step stays **synthetic-only** or introduces **sanitized / internal sample** extracts (governance, IRB, InfoSec).
- **Graph storage** — stay on CSV + Python for a while vs. spike **Neo4j** (or similar) and who would operate it.
- **NL and summarization** — when (if ever) to add **LLM** routing or narrative, and what **guardrails and logging** are non-negotiable.
- **Integration** — any near-term need to align with **existing case tools, catalogs, or reference architectures** at Manulife vs. continue as a standalone PoC.

We do not need to close all of these in one meeting; listing them helps prioritize.

---

## 6. Recommended next steps (1–2 weeks)

Practical and bounded — adjust based on team capacity:

1. **Walk the demo together** — one person shares screen: build graph → run app → hit 2–3 scenarios from `demo_cases.md`; note gaps in wording or flow.
2. **Assign one owner** for README “happy path” (fresh clone, venv, build, run) and fix any friction teammates hit.
3. **Pick one near-term enhancement** from `docs/roadmap.md` (e.g. richer seed row, one new query, or slightly better graph drawing) **or** explicitly defer enhancements and use the time for **stakeholder feedback** only.
4. **Capture decisions** — short notes after the meeting: what we demo next, what stays out of scope, and whether synthetic data remains the only input through the next milestone.

---

**Pointers:** Runbook — `README.md` · Demo script — `docs/demo_cases.md` · Data flow — `docs/technical_flow.md` · Longer horizon — `docs/roadmap.md`.
