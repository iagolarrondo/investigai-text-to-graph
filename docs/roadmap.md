# Roadmap — InvestigAI graph prototype

This is a **working plan**, not a commitment. It separates what we have today from **near-term** upgrades and a **longer-term** direction aligned with an enterprise fraud-investigation stack (for example at Manulife / John Hancock).

---

## 1. Current PoC v1 — what already works

- **Synthetic seed data** in `data/interim/poc_v1_seed/` with a small but coherent story (claims, policies, people, banks, addresses, businesses, crosswalks).
- **Graph build pipeline** (`build_graph_files.py`) that produces **`nodes.csv`** and **`edges.csv`** with stable ids and no dangling edge endpoints in normal runs.
- **Query layer** (`query_graph.py`): claim-centric neighborhood, shared bank accounts, person–person clusters, business–address colocation; outputs include tables plus short plain-English copy and supporting link bullets for demos.
- **Streamlit app** with predefined demo questions, free-text entry, **rule-based** natural-language routing (no external LLM required for v1), and a **small subgraph** view (tables + simple diagram).
- **Light automation**: pytest smoke tests on processed graph files; README and demo scenario docs for teammates.

**Boundary:** Everything runs **locally** on CSVs and in-memory Python. It is suitable for **proof of concept** and **stakeholder demos**, not for production decisions or real case data.

---

## 2. Next realistic improvements — short timeframe

These are incremental and **do not** assume a full platform rebuild.

| Area | Realistic next step |
|------|---------------------|
| **Richer synthetic data** | Add rows and edge types (e.g. providers, payments, phone/email overlap, time windows) while keeping the graph small enough to reason about in a meeting. |
| **More graph queries** | New investigation templates (e.g. shortest path between two entities, “all claims within N hops,” concentration by agent or bank routing number) reusing the same CSV + NetworkX pattern. |
| **Better graph visualization** | Swap or augment matplotlib with an interactive library (e.g. PyVis, or a lightweight D3 export) **only where** it improves readability without heavy setup. |
| **Improved natural language routing** | Add synonyms and fuzzy patterns, optional **small** LLM or embedding classifier **behind a feature flag**, with a clear fallback to rules when the model is off or uncertain. |
| **Tests & reproducibility** | Expand tests beyond file sanity (e.g. golden-row checks on one claim’s neighborhood after each build). |

Expect these to ship as **small PRs** or spikes, each demoable on its own.

---

## 3. Future-state vision — toward a target enterprise architecture

This section describes a **plausible evolution**, not a dated deliverable. Actual sequencing depends on security review, data access, and team capacity.

- **Real graph database (Neo4j / Cypher)**  
  Move from flat CSVs to a **managed or on-prem graph store** for larger books, indexed traversals, and shared access. The **conceptual** node and edge types from PoC v1 can inform a first Cypher model, but **schema and governance** would be redesigned with enterprise data owners.

- **Orchestration layer**  
  A small service (or workflow engine) that **schedules** extracts, graph refresh, feature flags, and **which** tools the UI may call—so the app is not a single monolith tied to one machine.

- **Unstructured data agent**  
  Optional pipeline that ingests **case notes, emails, or PDFs** (with strict redaction and policy), extracts entities and mentions, and **links or suggests** graph nodes—always with **human confirmation** before anything is treated as fact.

- **Stronger NL + guardrails**  
  If LLMs are used for routing or summarization: **prompt/version control**, logging, **refusal** on out-of-scope requests, and alignment with **audit** requirements—not “the model always knows.”

- **Integration, not replacement**  
  The end state is usually **adjacent** to existing SIU tools (case systems, watchlists), not a greenfield island. PoC v1 is intentionally small so those integration points can be named **later**, once the graph story is credible.

---

**Related docs:** [technical_flow.md](technical_flow.md) (data path), [demo_cases.md](demo_cases.md) (what to show today), [README.md](../README.md) (how to run).
