# Current Repository Inspection (Pre-change)

> **Stale snapshot:** This file described the repo **before** several PoC upgrades (synthetic pipeline, tool-planner investigation UI, **`src/session/`** memory + HTML export). For the **current** Streamlit flow, start with **[README.md](../README.md)** (investigation loop, session memory, entity resolution). Treat the sections below as historical context unless you are diffing against an old revision.

## Actual runtime flow (from code)

1. Operational seed CSVs live under `data/interim/poc_v1_seed/`.
2. `src/graph_build/build_graph_files.py` reads those tables, creates node IDs, and writes:
   - `data/processed/nodes.csv`
   - `data/processed/edges.csv`
3. `src/graph_query/query_graph.py` loads those processed CSVs into an in-memory `networkx.DiGraph`.
4. Investigation helpers query that graph (claim network, claim subgraph, shared banks, people clusters, business/address patterns).
5. `src/llm/router.py` uses Anthropic routing (`claude-opus-4-6`) to map free text to one of those predefined investigation functions.
6. `src/app/app.py` renders metrics, routed results, explanation text, and subgraph visualizations.

## Current operational schema actually consumed by graph build

Node seed tables:
- `t_resolved_person.csv`
- `t_resolved_business.csv`
- `t_norm_policy.csv`
- `t_norm_claim.csv`
- `t_resolved_address.csv`
- `t_resolved_bank_account.csv`

Relationship seed tables:
- `t_resolved_person_address_crosswalk.csv`
- `t_resolved_business_address_crosswalk.csv`
- `t_resolved_person_person_crosswalk.csv`
- `t_resolved_person_policy_crosswalk.csv`
- `t_resolved_person_bank_account_crosswalk.csv`

Synthetic edge rule in builder:
- `Claim -> Policy` is synthesized from `t_norm_claim.POLICY_NUMBER` as `IS_CLAIM_AGAINST_POLICY`.

## Important compatibility constraints observed in code

- `query_graph` logic expects specific node types and edge types already present in PoC data.
- App and router rely on those predefined query functions rather than arbitrary graph execution.
- Claim defaults include IDs such as `claim_C9000000001` / `claim_C9000000002` patterns.
- Builder drops edges if either endpoint node is missing, so seed referential integrity is critical.

## Gaps before this change

- No configurable large-scale synthetic generator.
- No seed/eval split for hidden scenario labels.
- No formal workflow to regenerate data in multiple sizes while preserving pipeline compatibility.

